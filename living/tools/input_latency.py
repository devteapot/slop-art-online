#!/usr/bin/env python3
"""Join opt-in authority, arena and mind timing evidence. Run with --help for inputs."""
import argparse
import json
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

from nav_report import phase_report, pct


def rows(file):
    with file.open() as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def capture_authority(url, db, token, destination, after_ms):
    """Keep only the diagnostic log lines. The authenticated log endpoint is owner-only."""
    request = urllib.request.Request(f"{url}/v1/database/{db}/logs?num_lines=200000",
                                     headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("w") as out:
        for line in response:
            record = json.loads(line)
            if int(record["ts"]) >= after_ms * 1000 and record["message"].startswith("input_latency "):
                out.write(json.dumps(record) + "\n")


def epoch_ms():
    return time.time_ns() / 1_000_000


def marks(file):
    for row in rows(file):
        _, stage, actor, key, reducer, tick, last, *detail = row["message"].split()
        yield dict(stage=stage, actor=int(actor), key=int(key), reducer_us=int(reducer),
                   last_tick=int(tick), last_tick_ms=int(last), wall_ms=int(row["ts"]) / 1000,
                   function=row.get("function"), detail=detail)


def fast_samples(authority, mind):
    by_issue = defaultdict(dict)
    tick_ends = {}
    for m in marks(authority):
        if m["stage"] == "tick_end":
            tick_ends[m["reducer_us"]] = m
        elif m["stage"].startswith(("fast_", "patch_")) and m["stage"] != "fast_trigger":
            by_issue[m["actor"], m["key"]][m["stage"]] = m
    picked = {(m["actor"], m["issued_ms"]): m for m in rows(mind)} if mind.exists() else {}
    for (actor, issue), by_stage in by_issue.items():
        if "fast_written" not in by_stage:
            continue
        written = by_stage["fast_written"]
        start = written["wall_ms"]
        trigger, first = map(int, written["detail"])
        m = picked.get((actor, issue), {})
        installed = by_stage.get("patch_installed")
        tick = tick_ends.get(written["reducer_us"], {}).get("key")
        trace = {"first_trigger_ms": first, "latest_trigger_ms": trigger, "issue_ms": issue,
                 "ask_written_ms": start, **m}
        for stage in ("patch_enter", "patch_installed", "patch_refused", "fast_done", "fast_expired"):
            if stage in by_stage:
                trace[stage + "_ms"] = by_stage[stage]["wall_ms"]
        if end := tick_ends.get(written["reducer_us"]):
            trace["tick_end_ms"] = end["wall_ms"]
        route = (
            ("issue_start_to_write", "issue_ms", "ask_written_ms"),
            ("write_through_sdk_callback", "ask_written_ms", "callback_ms"),
            ("sdk_callback_to_dispatch", "callback_ms", "dispatch_ms"),
            ("dispatch_to_task", "dispatch_ms", "picked_ms"),
            ("task_to_model_admission", "picked_ms", "model_start_ms"),
            ("model_admission_to_reply", "model_start_ms", "model_reply_ms"),
            ("reply_to_patch_send", "model_reply_ms", "patch_send_ms"),
            ("patch_send_to_authority_entry", "patch_send_ms", "patch_enter_ms"),
            ("authority_entry_to_install", "patch_enter_ms", "patch_installed_ms"),
        )
        spans = deltas(trace, route)
        spans.update(deltas(trace, (
            ("first_trigger_to_issue", "first_trigger_ms", "issue_ms"),
            ("latest_trigger_to_issue", "latest_trigger_ms", "issue_ms"),
            ("write_to_tick_end", "ask_written_ms", "tick_end_ms"),
            ("tick_end_through_sdk_callback", "tick_end_ms", "callback_ms"),
            ("install_to_reducer_result", "patch_installed_ms", "finished_ms"),
        )))
        terminal = next((s for s in ("patch_installed", "patch_refused", "fast_done", "patch_enter", "fast_expired") if s in by_stage), None)
        yield {"actor": actor, "issued_ms": issue, "issue_tick": tick,
               "terminal": terminal or ("mind_task" if m else "issued_no_completed_mind_trace"),
               "trace": trace, "spans_ms": spans,
               "total_ms": installed["wall_ms"] - issue if installed and m.get("error") is False else None}


def nav_samples(phase):
    config = json.loads((phase / "phase.json").read_text())
    walks = {(w["subject"], w["walk"]): w for w in rows(phase / "walks.jsonl")}
    by_actor = defaultdict(list)
    tick_ends = {}
    gates = set(config.get("gate_a", {}).get("ids", []))
    changes = defaultdict(list)
    for m in marks(phase / "input-latency-authority.jsonl"):
        by_actor[m["actor"]].append(m)
        if m["stage"] == "tick_end":
            tick_ends[m["reducer_us"]] = m["key"]
        if m["stage"] == "gate_changed" and m["key"] in gates and m["detail"][1] == "0":
            changes[m["key"]].append(m)
    reads = defaultdict(list)
    for line in (phase / "bodies.jsonl").read_text().splitlines():
        if not line.startswith("{"):
            continue
        update = json.loads(line)
        if "input_latency_read_ms" in update:
            for body in update.get("body", {}).get("inserts", []):
                reads[body["id"], body["t_ms"]].append(update["input_latency_read_ms"])
    for scored in phase_report(phase)["walks_detail"]:
        # N1 follows the prior rerun's pre-call censoring threshold. Keep main's
        # post-call score as well, since it can discard an immediate response.
        stims = scored.get("stimulus_ms", [])
        latencies = scored.get("latency_ms", [])
        if "pre_call_stimulus_ms" in scored:
            stims = [scored["pre_call_stimulus_ms"]]
            latencies = [scored["pre_call_latency_ms"]]
        actor = scored["subject"]
        walk = walks[actor, scored["walk"]]
        for stimulus, latency in zip(stims, latencies):
            events = by_actor[actor]

            def first(stage, start, end, match=lambda _: True):
                return next((m for m in events if m["stage"] == stage
                             and start <= m["wall_ms"] <= end and match(m)), None)

            trace = {"arena_stimulus_ms": stimulus}
            selected = {}
            segment = stimulus + latency if latency is not None else None
            if segment is not None:
                trace["segment_stamp_ms"] = segment
                selected["body_write"] = first("body_written", walk["order_send_wall_ms"],
                                               walk.get("end_ms", stimulus + 2000), lambda m: m["key"] == segment)
                if written := selected["body_write"]:
                    received = next((t for t in reads[actor, segment] if t >= written["wall_ms"]), None)
                    if received is not None:
                        trace["observer_read_ms"] = received
            if config["arena"] == "n1":
                trace.update({name: walk[name] for name in ("order_send_wall_ms", "order_ack_wall_ms")})
                reducer = "human_act" if config["kind"] == "click" else "mind_act"
                start, ack = trace["order_send_wall_ms"], trace["order_ack_wall_ms"]
                selected["input_entry"] = first(reducer, start, ack)
                selected["graph_install"] = first("graph_installed", start, ack)
                selected["act_queue"] = first("act_queued", start, ack)
                if install := selected["graph_install"]:
                    selected["graph_eval"] = first("graph_eval", install["wall_ms"], start + 2000,
                                                    lambda m: m["key"] == install["key"])
                if queued := selected["act_queue"]:
                    selected["act_attempt"] = first("act_attempt", queued["wall_ms"], start + 2000,
                                                    lambda m: m["detail"] == ["65534", "goto"])
                    selected["act_start"] = first("act_started", queued["wall_ms"], start + 2000,
                                                  lambda m: m["key"] == queued["key"])
                if ev := selected.get("graph_eval"):
                    selected["act_attempt"] = first("act_attempt", ev["wall_ms"], start + 2000,
                                                    lambda m: m["key"] == ev["key"] and m["detail"][-1] == "goto")
                terminal = next((stage for stage in ("body_write", "act_start", "act_attempt",
                                                      "graph_eval", "graph_install", "act_queue",
                                                      "input_entry") if selected.get(stage)), "input_sent")
            else:
                start = walk["order_ms"][0]
                selected["look"] = first("ground_look", stimulus, stimulus + 2000)
                selected["gate_memory"] = first("gate_remembered", start, stimulus + 2000,
                                                lambda m: m["key"] in gates and m["detail"][0] == "0")
                if gate := selected["gate_memory"]:
                    changed_ms = int(gate["detail"][1])
                    selected["gate_close"] = next((m for m in reversed(changes[gate["key"]])
                                                    if m["reducer_us"] // 1000 == changed_ms), None)
                selected["player_sweep"] = first("player_sweep", stimulus, stimulus + 2000)
                selected["graph_eval"] = first("graph_eval", stimulus, stimulus + 2000)
                selected["steer_blocked"] = first("steer_blocked", stimulus, stimulus + 2000)
                selected["motion_lost"] = first("motion_lost", stimulus, stimulus + 2000)
                terminal = ("body_write" if selected.get("body_write") else
                            "gate_memory_without_scored_response" if selected["gate_memory"] else
                            "ground_look_without_gate_write" if selected["look"] else
                            "geometric_stimulus_only")
            trace.update({name + "_ms": m["wall_ms"] for name, m in selected.items() if m})
            spans = deltas(trace, (
                ("send_to_input_entry", "order_send_wall_ms", "input_entry_ms"),
                ("input_entry_to_http_ack", "input_entry_ms", "order_ack_wall_ms"),
                ("input_entry_to_graph_install", "input_entry_ms", "graph_install_ms"),
                ("graph_install_to_eval", "graph_install_ms", "graph_eval_ms"),
                ("graph_eval_to_act_attempt", "graph_eval_ms", "act_attempt_ms"),
                ("input_entry_to_act_queue", "input_entry_ms", "act_queue_ms"),
                ("act_queue_to_start", "act_queue_ms", "act_start_ms"),
                ("act_attempt_to_body_write", "act_attempt_ms", "body_write_ms"),
                ("input_entry_to_body_write", "input_entry_ms", "body_write_ms"),
                ("gate_close_to_gate_memory", "gate_close_ms", "gate_memory_ms"),
                ("geometric_stimulus_to_ground_look", "arena_stimulus_ms", "look_ms"),
                ("geometric_stimulus_to_gate_memory", "arena_stimulus_ms", "gate_memory_ms"),
                ("geometric_stimulus_to_player_sweep", "arena_stimulus_ms", "player_sweep_ms"),
                ("geometric_stimulus_to_body_write", "arena_stimulus_ms", "body_write_ms"),
                ("body_write_through_observer_output", "body_write_ms", "observer_read_ms"),
            ))
            if selected.get("motion_lost") and latency is None:
                terminal = "motion_lost_without_scored_response"
            if latency is not None and not selected.get("body_write"):
                terminal = "scored_response_without_matching_write"
            response = selected.get("body_write")
            start = trace.get("order_send_wall_ms", stimulus)
            ticks = {name: tick_ends.get(m["reducer_us"]) if m["function"] == "tick" else m["last_tick"]
                     for name, m in selected.items() if m}
            # Keep the arena result beside the host-time split. Segment time may have been
            # re-anchored to an earlier point and is never used as a transaction timestamp.
            yield {"actor": actor, "walk": walk["walk"], "controller": config["kind"],
                   "terminal": terminal, "arena_latency_ms": latency,
                   "main_scanner_latency_ms": next(iter(scored.get("latency_ms", [])), None),
                   "arena_stimulus_clock_tick": walk.get("stimulus_tick"), "ticks": ticks,
                   "trace": trace, "spans_ms": spans,
                   "total_ms": response["wall_ms"] - start if response else None}


def deltas(trace, route):
    return {name: trace[end] - trace[start] for name, start, end in route if start in trace and end in trace}


def summary(samples):
    stages = sorted({k for s in samples for k in s["spans_ms"]})
    total = [s["total_ms"] for s in samples if s["total_ms"] is not None]
    # Share uses paired successful samples, sum(stage) / sum(total). Bounds and parallel
    # intervals can overlap. Keep their names explicit and do not sum their percentages.
    result = {}
    for stage in stages:
        values = [s["spans_ms"][stage] for s in samples if stage in s["spans_ms"]]
        paired = [(s["spans_ms"][stage], s["total_ms"]) for s in samples
                  if s["total_ms"] is not None and stage in s["spans_ms"]]
        den = sum(t for _, t in paired)
        result[stage] = quantiles(values) | {
            "share_pct": 100 * sum(v for v, _ in paired) / den if den > 0 else None,
            "share_n": len(paired),
        }
    return {"n": len(samples), "terminal": Counter(s["terminal"] for s in samples),
            "total": quantiles(total), "stages": result}


def quantiles(values):
    return {"n": len(values), "p50_ms": pct(values, .5), "p90_ms": pct(values, .9),
            "p95_ms": pct(values, .95), "negative_n": sum(v < 0 for v in values)}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    sub = cli.add_subparsers(dest="mode", required=True)
    fast = sub.add_parser("fast")
    fast.add_argument("run", type=Path, help="battle_diag run directory")
    nav = sub.add_parser("nav")
    nav.add_argument("phase", type=Path, nargs="+", help="one or more nav_arena phase directories")
    a = cli.parse_args()
    if a.mode == "fast":
        samples = list(fast_samples(a.run / "input-latency-authority.jsonl",
                                    a.run / "journal/outcomes/input_latency_fast.jsonl"))
        metadata = json.loads((a.run / "diag-result.json").read_text())
        start = metadata["measurement_start_ms"]
        stop = metadata["measurement_end_ms"]
        active = [s for s in samples if start <= s["issued_ms"] <= stop]
        result = {"summary": summary(active), "measurement_window_ms": [start, stop],
                  "outside_window_n": len(samples) - len(active), "samples": samples}
    else:
        result = {}
        for phase in a.phase:
            samples = list(nav_samples(phase))
            result[phase.name] = {"summary": summary(samples),
                                  "arena_score": quantiles([s["arena_latency_ms"] for s in samples if s["arena_latency_ms"] is not None]),
                                  "main_scanner_score": quantiles([s["main_scanner_latency_ms"] for s in samples if s["main_scanner_latency_ms"] is not None]),
                                  "samples": samples}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
