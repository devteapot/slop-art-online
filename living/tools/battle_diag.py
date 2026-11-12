#!/usr/bin/env python3
"""Where a battle of minded fighters spends the authority's tick, over time (docs/BATTLE_SCALE.md).
Free: the fake model; scratch `verify-minds-*` databases on the trial stack.

  battle_diag.py --run minds-bd-<stamp> [--battle 100] [--walkers 116] [--minutes 30]
                 [--window 30] [--period 60] [--no-mind] [--fast-lane]

Seed `island` (its residents and animals on their own rules). `--battle` minded people
(`spawn_crowd`) packed within 7 m of the battle site (where `spawn_battle` stages one) fight the
nearest person: strike; dodge or block when threatened; heal below half (knowing
wound_tending). `--walkers` more walk as foragers. A fighter who dies is replaced at the site
(the load generator's respawn, counted). The mind service thinks for all of them on the fake
model (think 5 s, compile 4 s, consolidation 4 s, talk 2 s), its compile keeping the fight graph,
unless `--no-mind` (requests to think then stay pending, refreshed with their scene).
`--fast-lane` sets the world law `fast_lane_on` (docs/FAST_LANE.md) and answers each fast call
after 1.0 s (r2e's model p50) with no change (`keep`), so the battle is the same as without it:
what it adds is the lane's own work (triggers, turns, the `fast_ask` rows, the replies). Each
sample then counts the fast calls of its window (`thought` rows of kind `fast`, by issue time) and
the `fast_ask` rows.

Every `--period` seconds a `--window`-second `bench.py` window (profiling on) gives the tick's
rate, durations and spans, and the authority's diagnostic counts for the window (`diag:` lines,
`common::report_diag`: percepts by kind and how many woke their observer, onlookers per
witnessed event, requests to think by reason, graph evaluations by trigger, scene renders); then
row counts of the tables that grow, this database's WASM memory and commitlog size from the
server's metrics, the alive population, respawns and the host's load. Until `--minutes` pass, or
two windows in a row run below 2 ticks a second (collapse). Evidence:
`.local/living/verify/<run>/diag.jsonl` (one line per sample) and `bench-*.json`.
"""
import argparse
import importlib.util
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("privacy", ROOT / ".agents/skills/verify-minds/scripts/privacy.py")
pv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pv)
vm = pv.vm
STDB = str(ROOT / "living/tools/stdb")
URL = os.environ.get("LIVING_STDB_URL", "http://127.0.0.1:3300").rstrip("/")
TABLES = ["character", "experience", "structure", "skill_use", "deliberation", "familiar", "combat_seen", "chronicle", "thought",
          "mind_state", "far_handle", "act_outcome", "line_heard", "inventory", "body", "vitals", "routine", "slumber", "relation", "judgment"]


def bench(run, label, seconds):
    out = run.directory / f"bench-{label}.json"
    env = dict(os.environ, LIVING_STDB=STDB)
    t0 = time.time()
    r = subprocess.run([sys.executable, str(ROOT / "living/tools/bench.py"), "--db", run.db, "--seconds", str(seconds), "--settle", "0",
                        "--log-lines", str(seconds * 30000 + 30000), "--out", str(out)], cwd=ROOT, env=env, capture_output=True, text=True)
    (run.directory / f"bench-{label}.log").write_text(r.stdout + r.stderr)
    if r.returncode:
        raise RuntimeError(f"bench {label} failed; see bench-{label}.log")
    return json.loads(out.read_text()), t0


def diag_counts(run, since, until):
    logs = subprocess.run([STDB, "logs", "-s", "local", run.db, "-n", "400000"], capture_output=True, text=True).stdout
    total, seconds = {}, 0
    for m in re.finditer(r"^(\S+Z)\s.*diag: (\{.*\})\s*$", logs, re.M):
        stamp = m.group(1)[:26].rstrip("Z")
        at = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%f" if "." in stamp else "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
        if since <= at <= until:
            seconds += 1
            for k, v in json.loads(m.group(2)).items():
                total[k] = total.get(k, 0) + v
    span = max(until - since, 1e-9)
    return {k: round(v / span, 1) for k, v in sorted(total.items())}, seconds


def count(run, table):
    out = subprocess.run([STDB, "sql", "-s", "local", run.db, f"SELECT COUNT(*) AS n FROM {table}"], capture_output=True, text=True).stdout
    nums = [l.strip() for l in out.splitlines() if l.strip().isdigit()]
    return int(nums[-1]) if nums else None


def metrics(ident):
    want = ("spacetime_worker_wasm_memory_bytes", "spacetime_message_log_size_bytes", "spacetime_worker_instance_operation_queue_length", "spacetime_module_log_file_size_bytes")
    out = {}
    try:
        text = urllib.request.urlopen(f"{URL}/v1/metrics", timeout=30).read().decode()
    except Exception as e:
        return {"error": str(e)}
    for line in text.splitlines():
        if line.startswith("#") or ident not in line:
            continue
        name = line.split("{", 1)[0]
        if name in ("reducer_wasm_time_usec_sum", "reducer_wasm_time_usec_count", "reducer_wasm_time_usec"):
            m = re.search(r'reducer="([^"]+)"', line)
            if m:
                key = f"{name}:{m.group(1)}"
                try:
                    out[key] = out.get(key, 0) + float(line.rsplit(" ", 1)[1])
                except ValueError:
                    pass
            continue
        if name in want:
            try:
                out[name] = out.get(name, 0) + float(line.rsplit(" ", 1)[1])
            except ValueError:
                pass
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True, help="a new run name starting with minds-")
    ap.add_argument("--battle", type=int, default=100)
    ap.add_argument("--walkers", type=int, default=116)
    ap.add_argument("--minutes", type=float, default=30)
    ap.add_argument("--window", type=int, default=30)
    ap.add_argument("--period", type=int, default=60)
    ap.add_argument("--no-mind", action="store_true")
    ap.add_argument("--fast-lane", action="store_true", help="the world law fast_lane_on true; fast calls answered `keep` after 1.0 s")
    a = ap.parse_args()
    run = vm.Run(a.run)
    state = {"respawns": 0, "stop": False, "fighters": []}
    head = {}
    try:
        run.harness("launch", "--seed", "island")
        run.harness("doctor")
        if a.fast_lane:
            run.admin("set_world_law", "fast_lane_on", "true")
        listing = subprocess.run([STDB, "list", "-s", "local"], capture_output=True, text=True).stdout
        ident = next((l.split("|")[1].strip() for l in listing.splitlines() if l.split("|")[0].strip() == run.db), "")
        before = {c["id"] for c in run.sql("SELECT id FROM character", "chars-0")}
        run.admin("spawn_battle", 1)
        probe = [c for c in run.sql("SELECT id FROM character", "chars-probe") if c["id"] not in before]
        site = next(b for b in run.private("SELECT id, x, y FROM body", "bodies-probe") if b["id"] == probe[0]["id"])
        run.admin("kill", probe[0]["id"], "diag probe")
        site = (site["x"], site["y"])
        graph = lambda id: {"first": [
            {"if": {"cond": {"health": {"below": 50}}, "then": {"do": {"skill": "heal", "target": "self"}}}},
            {"if": {"cond": {"threatened": True}, "then": {"do": {"skill": "dodge" if id % 2 == 0 else "block"}}}},
            {"do": {"skill": "strike", "target": {"nearest": "person"}}}]}

        def spawn(n):
            have = {c["id"] for c in run.sql("SELECT id FROM character", "chars")}
            run.admin("spawn_crowd", n, True)
            # Only the ones spawned (a resident's child born meanwhile is new too).
            return sorted(c["id"] for c in run.sql("SELECT id, name, alive FROM character", "chars") if c["id"] not in have and c["name"].startswith("Walker") and c["alive"])

        def fighter(id):
            try:
                run.admin("place_at", id, site[0] + random.uniform(-7, 7), site[1] + random.uniform(-7, 7))
                run.admin("grant_items", id, "spear", 1)
                run.admin("grant_know_how", id, "wound_tending")
                run.admin("set_behavior", id, json.dumps(graph(id)))
            except RuntimeError:
                # Gone before it was set up (killed at once in the press): the keeper replaces it.
                pass

        made = spawn(a.battle + a.walkers)
        fighters = made[: a.battle]
        for id in fighters:
            fighter(id)
        state["fighters"] = list(fighters)
        if not a.no_mind:
            replies = {"think": {"thought": "diag fixture: I keep fighting.", "intend": [], "say": None, "judgments": []},
                       # The compile reinstalls the fight (a compile that kept "the current plan"
                       # replaced the fighters' graphs in the first run, and the battle stopped).
                       "deliberate": {"graph": "keep", "plan": "diag fixture"}, "talk": {"thought": "diag fixture", "say": None, "end": True},
                       "consolidate": {"summary": "diag fixture", "remember": [], "nodes": [], "edges": [], "retract": [], "merge": [], "identity": None,
                                       "relations": [], "judgments": [], "places": []}}
            # A fighter's compile reinstalls its fight; anyone else's keeps its plan. (In the first run a compile that kept "the current plan"
            # replaced the fighters' graphs and the battle stopped.)
            # Fighters are the first spawned (Walker1..Walker<battle>; a refill's names start at 1
            # again), and a prompt opens "# Who you are (<name>)".
            fight = [{"purpose": "deliberate", "contains": f"# Who you are (Walker{n})", "delay_s": 4.0, "times": -1,
                      "reply": {"graph": graph(0), "plan": "diag fixture: keep fighting", "weight": 1.5}} for n in range(1, a.battle + 1)]
            replies["fast"] = {"keep": True, "thought": "diag fixture: as it is."}
            script = {"replies": replies, "rules": fight + [{"purpose": p, "delay_s": d, "times": -1, "reply": replies[p]} for p, d in (("think", 5.0), ("deliberate", 4.0), ("consolidate", 4.0), ("talk", 2.0), ("fast", 1.0))]}
            # The minds of everyone spawned, and of the fighters spawned later to refill the battle:
            # ids are handed out in order, so the next few thousand are theirs (an empty
            # LIVING_ONLY would mean no one).
            ids = list(made) + list(range(max(made) + 1, max(made) + 4001))
            run.start(vm.model(run, script), ids, seed="island", extra_env={"LIVING_CONCURRENCY": "64"})

        def keep_battle():
            while not state["stop"]:
                try:
                    alive = {c["id"] for c in run.sql("SELECT id, alive FROM character", "alive") if c["alive"]}
                    dead = [f for f in state["fighters"] if f not in alive]
                    for f in dead:
                        state["fighters"].remove(f)
                    if dead:
                        for id in spawn(len(dead)):
                            fighter(id)
                            state["fighters"].append(id)
                            state["respawns"] += 1
                except Exception as e:
                    (run.directory / "keeper-error.txt").write_text(str(e))
                time.sleep(3)

        keeper = threading.Thread(target=keep_battle, daemon=True)
        keeper.start()
        head = {"battle": a.battle, "walkers": a.walkers, "site": site, "ambient_at_publish": len(before), "mind": not a.no_mind, "fast_lane": a.fast_lane,
                "nproc": os.cpu_count(), "db_identity": ident}
        (run.directory / "diag-head.json").write_text(json.dumps(head, indent=1))
        print(json.dumps(head), flush=True)
        t_start, low, k = time.time(), 0, 0
        while time.time() - t_start < a.minutes * 60:
            k += 1
            load0 = os.getloadavg()[0]
            b, t0 = bench(run, f"{k:02d}", a.window)
            t1 = t0 + 1.2 + a.window
            d, secs = diag_counts(run, t0, t1 + 1)
            t, sp = b["tick_ms"], b["spans_ms"]
            sample = {"k": k, "t_min": round((t0 - t_start) / 60, 1), "ticks_per_s": b["ticks_per_s"], "tick_p50": t["p50"], "tick_p99": t["p99"], "tick_max": t["max"],
                      "over_16_7": t["over_16_7ms"], "tick_samples": t["samples"], "spans_ms_s": {n: v["ms_per_s"] for n, v in sp.items() if v["ms_per_s"] >= 1.0},
                      "spans_n": {n: v["n"] for n, v in sp.items() if n.startswith(("perceive.", "brain."))}, "stats": {x: b.get(x) for x in ("evals_per_s", "experiences_per_s", "deliberation_requests_per_s", "motions_per_s")},
                      "diag_per_s": d, "diag_seconds": secs, "load_1m": [round(load0, 1), round(os.getloadavg()[0], 1)], "respawns": state["respawns"]}
            sample["rows"] = {tb: count(run, tb) for tb in TABLES}
            sample["alive"] = sum(1 for c in run.sql("SELECT id, alive FROM character", "census") if c["alive"])
            if a.fast_lane:
                # Fast calls whose request was issued in this window, from their `thought` rows.
                fast = []
                for r in run.private("SELECT kind, detail, at_ms FROM thought WHERE kind = 'fast'", f"fast-{k:02d}"):
                    try:
                        issued = json.loads(r["detail"]).get("issued_ms") or r["at_ms"]
                    except (ValueError, TypeError):
                        issued = r["at_ms"]
                    fast.append(issued)
                w0, w1 = t0 * 1000, t1 * 1000
                sample["fast"] = {"calls_in_window": sum(1 for x in fast if w0 <= x < w1), "per_s": round(sum(1 for x in fast if w0 <= x < w1) / a.window, 3),
                                  "total": len(fast), "fast_ask_rows": count(run, "fast_ask")}
            sample["metrics"] = metrics(ident) if ident else {}
            with (run.directory / "diag.jsonl").open("a") as f:
                f.write(json.dumps(sample) + "\n")
            print(json.dumps({x: sample[x] for x in ("k", "t_min", "ticks_per_s", "tick_p50", "over_16_7", "alive", "respawns", "load_1m")} | {"exp_s": sample["stats"]["experiences_per_s"], "experience_rows": sample["rows"]["experience"]}), flush=True)
            low = low + 1 if b["ticks_per_s"] < 2 else 0
            if low >= 2:
                print("collapse: two windows below 2 ticks a second", flush=True)
                break
            time.sleep(max(0, a.period - (time.time() - t0)))
        head["status"] = "done"
    except Exception as error:
        (run.directory / "failure.txt").write_text(traceback.format_exc())
        head["status"] = f"fail: {type(error).__name__}: {error}"
    finally:
        state["stop"] = True
        # The harness pauses the world and reads it back as paused before deleting it
        # (living/tools/world_delete.py).
        run.finish_cleanup()
        (run.directory / "diag-result.json").write_text(json.dumps(head, indent=1))
        print(json.dumps(head), flush=True)
    return 0 if head.get("status") == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
