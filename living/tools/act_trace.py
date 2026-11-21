#!/usr/bin/env python3
"""Deliberate acts' course from the authority's `latency_acts` markers (docs/INPUT_LATENCY.md,
"Mind acts replace"). Python standard library and docker.

    act_trace.py capture --container C --replica N --out act-trace.jsonl [--after-ms MS]
    act_trace.py report act-trace.jsonl [--actors FILE] [--seconds S] [--from-ms MS] [--to-ms MS]
    act_trace.py firstwrite PHASE_DIR ...

`firstwrite` reads nav_arena.py phases' `input-latency-authority.jsonl` (the arena's subjects are
traced under `latency_nav_from`): for each order (`mind_act` or `human_act` entry), the wall ms to
its act's start and to the first `body_written` of that subject after the start, and whether
another act was in progress at the order.

`capture` reads a replica's whole module log from the server's data directory (the API tail drops
lines on a busy world) and keeps the `input_latency act_*` markers. `report` follows each
character's acts through them, one act in progress at a time:

- `act_submit` (key: acts in the batch; detail: source, player, replace), `act_dropped` (key:
  acts that were waiting when a replacing batch came), `act_queued` (key: queue id),
  `act_started` (key: queue id), `act_refused` / `act_expired` (key: queue id), `act_replaced`
  (key: the act's start ms; detail: skill, phase, age ms, source), `act_done` (key: start ms;
  detail: ok, code, skill, phase, age ms), `act_set_aside` (a reflex dropped what was waiting),
  `act_continued` (key: queue id; the same act again went on, `act_same_continues`) and
  `act_rate_refused` (a call refused by the input bucket, `act_input_cost`: nothing queued).
  Since act-replace-gaps `act_replaced` comes after the new act's `act_queued`, when it starts.

It reports the queue wait of each batch's first act (queued → started, wall ms of the log
records) split by whether another act was in progress when the batch came; the fate of every started act (done, failed by code,
replaced in its approach or its performance); acts that never started (dropped, expired, refused,
still waiting); and replacements per character-second over `--seconds` for the characters in
`--actors` (a JSON list of ids; default every actor seen).
"""
import argparse
import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPLICAS = "/home/spacetime/.local/share/spacetime/data/replicas"


def newest_replica(container):
    r = subprocess.run(["docker", "exec", container, "sh", "-c", f"ls -1 {REPLICAS}"], capture_output=True, text=True, timeout=60)
    return max(int(x) for x in r.stdout.split() if x.isdigit())


def capture(container, replica, out, after_ms=0):
    d = f"{REPLICAS}/{replica}/module_logs"
    r = subprocess.run(["docker", "exec", container, "sh", "-c", f"cat $(ls -1 {d}/* | sort)"], capture_output=True, timeout=900)
    n = 0
    with open(out, "w") as f:
        for line in r.stdout.decode("utf-8", "replace").splitlines():
            if "input_latency act_" not in line:
                continue
            try:
                j = json.loads(line)
            except ValueError:
                continue
            if int(j.get("ts", 0)) < after_ms * 1000:
                continue
            f.write(json.dumps({"ts": j["ts"], "message": j["message"]}) + "\n")
            n += 1
    return n


def marks(path):
    with open(path) as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            _, stage, actor, key, reducer, tick, last, *detail = row["message"].split()
            yield dict(stage=stage, actor=int(actor), key=int(key), reducer_us=int(reducer), wall_ms=int(row["ts"]) / 1000, detail=detail)


def done_at_start(rows, i):
    """Whether the act started at `rows[i]` (`act_started`) was already done in its own transaction:
    an act with nothing to do (a walk to where the body stands) completes inside `begin`, so its
    `act_done` (age 0, key its start ms) is logged before its `act_started`, in the same transaction."""
    m = rows[i]
    for x in reversed(rows[max(0, i - 40):i]):
        if x["reducer_us"] != m["reducer_us"]:
            break
        if x["actor"] == m["actor"] and x["stage"] == "act_done" and x["detail"] and x["detail"][-1] == "0":
            return True
    return False


def pct(values, q):
    v = sorted(values)
    if not v:
        return None
    k = (len(v) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return round(v[lo] + (v[hi] - v[lo]) * (k - lo), 2)


def dist(values):
    return {"n": len(values), "p50": pct(values, 0.5), "p90": pct(values, 0.9), "p95": pct(values, 0.95), "max": round(max(values), 2) if values else None}


def report(path, actors=None, seconds=None, from_ms=None, to_ms=None):
    rows = sorted(marks(path), key=lambda m: (m["wall_ms"], m["reducer_us"]))
    if from_ms is not None:
        rows = [m for m in rows if m["wall_ms"] >= from_ms]
    if to_ms is not None:
        rows = [m for m in rows if m["wall_ms"] <= to_ms]
    if actors is not None:
        rows = [m for m in rows if m["actor"] in actors]
    stages = Counter(m["stage"] for m in rows)
    sources = Counter(m["detail"][0] for m in rows if m["stage"] == "act_submit")
    replacing = Counter(m["detail"][2] for m in rows if m["stage"] == "act_submit")
    running = {}  # actor -> started act (skill, start wall ms)
    queued = {}  # queue id -> (wall ms, actor, busy at submit)
    busy_at = {}  # actor -> whether an act was in progress at its last submit
    first_of_batch = {}
    waits = {"after_idle": [], "behind_act": []}
    fates = Counter()
    replaced = {"approach": [], "performing": []}
    replaced_by_skill = Counter()
    done_ok, done_fail = Counter(), Counter()
    never = Counter()
    started_skills = Counter()
    for i, m in enumerate(rows):
        a, st = m["actor"], m["stage"]
        if st == "act_submit":
            busy_at[a] = a in running
            first_of_batch[a] = True
        elif st == "act_queued":
            # Only a batch's first act is timed: the later ones wait for the batch's own earlier acts.
            queued[m["key"]] = (m["wall_ms"], a, busy_at.get(a, a in running), first_of_batch.pop(a, False))
        elif st == "act_started":
            q = queued.pop(m["key"], None)
            if q and q[3]:
                waits["behind_act" if q[2] else "after_idle"].append(m["wall_ms"] - q[0])
            # An act done in its own transaction (`done_at_start`) holds nothing afterwards.
            if not done_at_start(rows, i):
                running[a] = (m["detail"][0] if m["detail"] else "?", m["wall_ms"])
            started_skills[m["detail"][0] if m["detail"] else "?"] += 1
        elif st in ("act_refused", "act_expired"):
            queued.pop(m["key"], None)
            never[st] += 1
        elif st == "act_continued":
            # The same act again while it ran, absorbed by it (`act_same_continues`): not a start.
            queued.pop(m["key"], None)
            fates["continued_by_the_same"] += 1
        elif st in ("act_dropped", "act_set_aside"):
            never["dropped_by_replacement" if st == "act_dropped" else "set_aside_by_reflex"] += m["key"]
            for q in [q for q, v in queued.items() if v[1] == a]:
                del queued[q]
        elif st == "act_replaced":
            skill, phase, age = m["detail"][0], int(m["detail"][1]), int(m["detail"][2])
            replaced["performing" if phase == 1 else "approach"].append(age)
            replaced_by_skill[skill] += 1
            fates["replaced"] += 1
            running.pop(a, None)
        elif st == "act_done":
            ok, code, skill = m["detail"][0] == "1", m["detail"][1], m["detail"][2]
            (done_ok if ok else done_fail)[f"{skill} {code}" if not ok else skill] += 1
            fates["done" if ok else f"failed:{code}"] += 1
            running.pop(a, None)
    never["still_waiting_at_end"] = len(queued)
    fates["still_running_at_end"] = len(running)
    started = sum(started_skills.values())
    who = actors if actors is not None else {m["actor"] for m in rows}
    out = {
        "markers": dict(stages), "submits_by_source": dict(sources), "submits_replacing": dict(replacing),
        "first_act_queue_wait_ms": {k: dist(v) for k, v in waits.items()},
        "first_act_queue_wait_all_ms": dist(waits["after_idle"] + waits["behind_act"]),
        "started": started, "started_by_skill": dict(started_skills.most_common()),
        "fate_of_started": dict(fates),
        "replaced_age_ms": {k: dist(v) for k, v in replaced.items()},
        "replaced_by_skill": dict(replaced_by_skill.most_common()),
        "done_ok_by_skill": dict(done_ok.most_common()), "failed_by_skill_code": dict(done_fail.most_common(20)),
        "never_started": dict(never),
        "share_started_replaced": round(fates["replaced"] / started, 4) if started else None,
        "share_started_done_ok": round(fates["done"] / started, 4) if started else None,
        "characters": len(who),
    }
    if seconds:
        out["seconds"] = seconds
        out["replacements_per_character_second"] = round(fates["replaced"] / (len(who) * seconds), 6) if who else None
        out["replacements_per_character_minute"] = round(60 * fates["replaced"] / (len(who) * seconds), 4) if who else None
    return out


def firstwrite(phases):
    out = {}
    for phase in phases:
        rows = sorted(marks(Path(phase) / "input-latency-authority.jsonl"), key=lambda m: (m["wall_ms"], m["reducer_us"]))
        samples = []
        for i, m in enumerate(rows):
            if m["stage"] not in ("mind_act", "human_act"):
                continue
            a = m["actor"]
            later = [x for x in rows[i + 1:] if x["actor"] == a]
            nxt = next((x for x in later if x["stage"] in ("mind_act", "human_act")), None)
            window = [x for x in later if nxt is None or x["wall_ms"] < nxt["wall_ms"] or x is nxt]
            start = next((x for x in window if x["stage"] == "act_started"), None)
            # The act's begin writes the body before `act_started` is logged, in the same
            # transaction: the first write at or after the act's attempt (`act_attempt`) there.
            attempt = start and next((x for x in window if x["stage"] == "act_attempt" and x["reducer_us"] == start["reducer_us"]), None)
            since = attempt or start
            write = next((x for x in window if since and x["stage"] == "body_written" and
                          (x["reducer_us"] == since["reducer_us"] and x["wall_ms"] >= since["wall_ms"] or x["wall_ms"] > start["wall_ms"])), None)
            busy = any(x["stage"] == "act_queued" for x in window) and start is not None and \
                next((x for x in window if x["stage"] == "act_queued"), m)["reducer_us"] != start["reducer_us"]
            samples.append({"actor": a, "entry_ms": m["wall_ms"], "to_start_ms": start and round(start["wall_ms"] - m["wall_ms"], 3),
                            "to_first_write_ms": write and round(write["wall_ms"] - m["wall_ms"], 3), "started_later_tx": busy})
        out[Path(phase).name] = {"orders": len(samples),
                                 "to_start_ms": dist([s["to_start_ms"] for s in samples if s["to_start_ms"] is not None]),
                                 "to_first_write_ms": dist([s["to_first_write_ms"] for s in samples if s["to_first_write_ms"] is not None]),
                                 "started_in_a_later_transaction": sum(s["started_later_tx"] for s in samples),
                                 "no_start": sum(s["to_start_ms"] is None for s in samples),
                                 "samples": samples}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["capture", "report", "firstwrite"])
    ap.add_argument("trace", nargs="*")
    ap.add_argument("--container")
    ap.add_argument("--replica", type=int)
    ap.add_argument("--out")
    ap.add_argument("--after-ms", type=int, default=0)
    ap.add_argument("--actors")
    ap.add_argument("--seconds", type=float)
    ap.add_argument("--from-ms", type=float)
    ap.add_argument("--to-ms", type=float)
    a = ap.parse_args()
    if a.step == "capture":
        replica = a.replica if a.replica is not None else newest_replica(a.container)
        print(capture(a.container, replica, a.out, a.after_ms))
        return 0
    if a.step == "firstwrite":
        print(json.dumps(firstwrite(a.trace), indent=1))
        return 0
    actors = set(json.loads(Path(a.actors).read_text())) if a.actors else None
    print(json.dumps(report(a.trace[0], actors, a.seconds, a.from_ms, a.to_ms), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
