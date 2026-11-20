#!/usr/bin/env python3
"""The public-feed scoping cost gate (docs/FEED_SCOPING.md, "Cost gate"; docs/COVER_SIGHT.md,
"Switch-on gate"): interleaved off/on arms on a private SpacetimeDB server, under the Spark
battle lock, taken once for the whole series.

Arms differ only in the `feed_scope_on` law: off is a world at stage 0 whose players subscribe the
game client's legacy set (whole `gate`, `structure` and `resource_node` windows); on is the same
world taken to stage 2 (`feed_scope_grace_s` 1) before its players connect, subscribing the scoped
set (`map_structure`/`map_resource` windows and the sender-scoped `my_things`,
`my_remembered_things`, `my_owners`, `my_stock`, `my_fuel_seen`). Cover is on in every arm; Round
has facing and gaze off, Middle and the woods have them on.

Workloads: `round` and `middle` (Cullet, 64 residents and 152 walking SDK clients in seven
clusters, 216 live) and `woods` (the archived cover-acceptance land, 96 fighters with
reduced-damage spears round (276, 224), 48 staged remains, 8 walking SDK witnesses). Each run
waits for a one-minute load average under 6 (`--max-load`) before it launches and records the
load, memory and disk at start and end; tick and sight spans come from the full server module
log for the profiled window (not the CLI's tail).

    LIVING_STDB_CONTAINER=slop-feedscope-stdb LIVING_STDB_URL=http://127.0.0.1:3431 \\
    CARGO_TARGET_DIR=~/slop-feedscope-build-target \\
    python3 living/tools/feed_scope_cost.py --series fs1 --woods-seed .local/feedscope/woods.json
"""
import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent))
import battle_diag as battle  # noqa: E402
import look_cost as load  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
VERIFY = ROOT / ".agents/skills/verify/scripts/verify.py"
REPLICAS = "/home/spacetime/.local/share/spacetime/data/replicas"
SPAN = re.compile(r'^Timing span "([^"]+)": ([\d.]+)(µs|ms|s)\b')
UNITS = {"µs": 0.001, "ms": 1, "s": 1000}
NEEDLES = (b'Timing span \\"tick\\"', b'Timing span \\"sight.', b'Timing span \\"scene.sensed\\"', b'"message":"diag: ', b'feed scope pop-in')
POPIN = re.compile(r"^feed scope pop-in: (\d+) ms at ([\d.]+) m")
POPIN_MISSED = re.compile(r"^feed scope pop-in missed: in sight (\d+) ms at ([\d.]+) m")
# The Spark's fast cores (X925; docs/COMBAT_PHASE.md on combat-phase): every arm's server is pinned.
FAST_CPUS = "5-9,15-19"
# Spans timed inside another sight span (not summed).
NESTED = {"sight.gather"}
COMMON = ["cover_law", "feed_scope", "my_offers", "my_known_names", "my_earshot", "speech_card", "my_records", "heard_sounds", "my_senses", "my_act_outcomes"]
FEEDS = {"off": ["gate"], "on": ["my_things", "my_remembered_things", "my_owners", "my_stock", "my_fuel_seen", "my_contents_seen"]}
# The probe arm: on, with `feed_scope_popin_probe` (it tests more than on does; its cost is not the
# arm's, only its pop-in delays are read).
FEEDS["probe"] = FEEDS["on"]
# The check arm: on, with `feed_scope_loop_check` (iteration 4's short pass against iteration 3's
# walk on the same state, every sweep); not a cost arm, only its counts are read.
FEEDS["check"] = FEEDS["on"]


def host():
    mem = int(next(line.split()[1] for line in Path("/proc/meminfo").read_text().splitlines() if line.startswith("MemAvailable:")))
    return dict(time=time.strftime("%Y-%m-%dT%H:%M:%S%z"), load=os.getloadavg(), available_memory_kib=mem, free_disk_bytes=shutil.disk_usage(ROOT).free)


# The coordinator may close the night's reclaim window early (`--reclaim-closed`): then only
# 23:15-24:00 stays closed.
RECLAIM_CLOSED = False


def in_window():
    hour, minute = map(int, time.strftime("%H:%M").split(":"))
    if hour * 60 + minute >= 23 * 60 + 15:
        return False
    return RECLAIM_CLOSED or hour >= 2


def check_host():
    if not in_window():
        raise RuntimeError("outside the permitted measurement window (02:00-23:15)")
    info = host()
    if info["available_memory_kib"] < 40 * 1024**2 or info["free_disk_bytes"] < 45 * 1024**3:
        raise RuntimeError(f"resource floor: {info}")
    return info


def wait_load(limit, most_s):
    """Wait for the one-minute load average under `limit`; never measure above it. The wait ends
    when the measurement window closes (or after `most_s`), which stops the series."""
    t0 = time.time()
    while os.getloadavg()[0] >= limit:
        if not in_window() or time.time() - t0 > most_s:
            raise SystemExit(f"load stayed at or above {limit} for {round(time.time() - t0)} s (now {os.getloadavg()}): stopping the series")
        time.sleep(15)
    return {"waited_s": round(time.time() - t0), "load": os.getloadavg(), "under": True}


def parse_log(path, start, end, popin=None):
    spans, diags, periods = defaultdict(list), Counter(), 0
    with path.open("rb") as source:
        for line in source:
            if not any(n in line for n in NEEDLES):
                continue
            event = json.loads(line)
            if not start <= event["ts"] / 1_000_000 < end:
                continue
            message = event["message"]
            if message.startswith("diag: "):
                diags.update(json.loads(message[6:]))
                periods += 1
                continue
            m = SPAN.match(message)
            if m:
                name, duration, unit = m.groups()
                spans[name].append(float(duration) * UNITS[unit])
                continue
            if popin is not None:
                m = POPIN.match(message)
                if m:
                    popin["delays_ms"].append(int(m.group(1)))
                    popin["dist_m"].append(float(m.group(2)))
                    continue
                m = POPIN_MISSED.match(message)
                if m:
                    popin["missed_in_sight_ms"].append(int(m.group(1)))
    return spans, diags, periods


def quantiles(v):
    if not v:
        return {"n": 0}
    v = sorted(v)
    q = lambda f: v[min(len(v) - 1, int(f * len(v)))]
    return {"n": len(v), "p50": q(0.5), "p90": q(0.9), "max": v[-1], "zero_share": sum(x == 0 for x in v) / len(v)}


def pin(container):
    """Pin the private measurement server to the fast cores and say where it runs."""
    subprocess.run(["docker", "update", "--cpuset-cpus", FAST_CPUS, container], check=True, capture_output=True)
    got = subprocess.run(["docker", "inspect", "-f", "{{.HostConfig.CpusetCpus}}", container], text=True, capture_output=True, check=True).stdout.strip()
    if got != FAST_CPUS:
        raise RuntimeError(f"{container} is on CPUs {got!r}, not {FAST_CPUS}")
    return got


def merge_running():
    """A merge holds ~/slop-mq/lock: no measuring meanwhile."""
    path = Path.home() / "slop-mq/lock"
    if not path.exists():
        return False
    with path.open("r") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(f, fcntl.LOCK_UN)
    return False


def module_log(ident, dest):
    logs = subprocess.run(["docker", "logs", load.CONTAINER], text=True, capture_output=True, check=True)
    replicas = dict(re.findall(r"launching module db=([0-9a-f]+) replica=([1-9][0-9]*)", logs.stdout + logs.stderr))
    replica = replicas.get(ident)
    if not replica:
        raise RuntimeError(f"no replica for {ident}")
    with dest.open("wb") as out:
        subprocess.run(["docker", "exec", load.CONTAINER, "sh", "-c", f"cat {REPLICAS}/{replica}/module_logs/*.log"], check=True, stdout=out)


def one(name, workload, arm, seconds, woods_seed, max_load):
    evidence = ROOT / ".local/living/verify" / name
    evidence.mkdir(parents=True, exist_ok=False)
    db = f"verify-{name}"
    binary = Path(os.environ["CARGO_TARGET_DIR"]) / "release/gate-load"
    seed = str(woods_seed.with_suffix("")) if workload == "woods" else "cullet"

    def harness(command, *extra):
        with (evidence / "harness.log").open("a") as log:
            prefix = [str(Path.home() / "slop-mq/build-slot")] if command == "launch" else []
            subprocess.run([*prefix, sys.executable, str(VERIFY), command, "--run", name, *extra], stdout=log, stderr=subprocess.STDOUT, check=True)

    load.stdb = lambda *cli, timeout=180: load.sh("docker", "exec", "-i", load.CONTAINER, "spacetime", *cli, timeout=timeout)
    client = None
    attempted = False
    try:
        while merge_running():
            if not in_window():
                raise SystemExit("a merge held ~/slop-mq/lock until the window closed: stopping the series")
            time.sleep(15)
        placement = pin(load.CONTAINER)
        waited = wait_load(max_load, 6 * 3600)
        (evidence / "host-before-launch.json").write_text(json.dumps({**check_host(), "load_wait": waited}))
        attempted = True
        harness("launch", "--seed", seed, "--target-dir", os.environ["CARGO_TARGET_DIR"])
        harness("doctor")
        owner = load.admin_token()

        def sql(query):
            return load.sql(db, query, owner)

        def call(reducer, *values):
            load.call(db, reducer, values, owner)

        laws = {"profile_detail": True, "cover_sight_on": True, "fov_on": workload != "round", "gaze_on": workload != "round"}
        for key, value in laws.items():
            call("set_world_law", key, json.dumps(value))
        if arm in ("on", "probe", "check"):
            call("set_world_law", "feed_scope_grace_s", "1")
            call("set_world_law", "feed_scope_on", "true")
            if arm == "probe":
                call("set_world_law", "feed_scope_popin_probe", "true")
            if arm == "check":
                call("set_world_law", "feed_scope_loop_check", "true")
            t0 = time.time()
            while (sql("SELECT stage FROM feed_scope") or [{"stage": 0}])[0]["stage"] != 2:
                if time.time() - t0 > 30:
                    raise RuntimeError("the world did not reach stage 2")
                time.sleep(0.5)

        def census():
            return {row["id"]: row for row in sql("SELECT id, name, alive FROM character") if row["alive"]}

        ambient = len(census())
        fighters, center = [], (0, 0)
        if workload == "woods":
            call("set_paused", True)
            for key in ("dmg_strike", "dmg_strike_spear"):
                call("set_world_law", key, "0.05")
            before = census()
            call("spawn_crowd", 96, True)
            fighters = sorted(census().keys() - before.keys())
            if len(fighters) != 96:
                raise RuntimeError(f"expected 96 fighters, got {len(fighters)}")
            center = (276, 224)
            tiles, positions = {}, []
            for y in range(216, 233):
                for x in range(268, 285):
                    chunk = (y // 16 << 16) | x // 16
                    if chunk not in tiles:
                        row, = sql(f"SELECT tiles FROM terrain_chunk WHERE id = {chunk}")
                        data = row["tiles"]
                        tiles[chunk] = bytes.fromhex(data.removeprefix("0x")) if isinstance(data, str) else bytes(data)
                    if tiles[chunk][(y % 16) * 16 + x % 16] in (0, 1, 3, 5, 6):
                        positions.append((x + 0.5, y + 0.5))
            positions.sort(key=lambda xy: (math.dist(xy, center), xy))
            if len(positions) < 96:
                raise RuntimeError("too few walkable wooded tiles")
            for index, (fighter, at) in enumerate(zip(fighters, positions)):
                call("place_at", fighter, *at)
                call("grant_items", fighter, "spear", 1)
                call("set_behavior", fighter, json.dumps({"first": [
                    {"if": {"cond": {"threatened": True}, "then": {"do": {"skill": "dodge" if index % 2 else "block"}}}},
                    {"do": {"skill": "strike", "target": {"nearest": "person"}}},
                ]}))
                if index % 2 == 0:
                    call("place_structure", fighter, "remains")
            call("set_paused", False)
            count = 8
            spots = [(center[0] + 8 * math.cos(i * math.tau / count), center[1] + 8 * math.sin(i * math.tau / count)) for i in range(count)]
        else:
            if ambient != 64:
                raise RuntimeError(f"expected 64 Cullet residents, got {ambient}")
            count = 152
            _, spots = load.clusters(sql("SELECT * FROM lot"), 7, 3.0, -(-count // 7))

        tokens = [load.new_identity() for _ in range(count)]
        client = load.Proc([binary, "players"], evidence / "players.stderr")
        client.send(json.dumps({
            "uri": load.URL, "db": db, "events": str(evidence / "events.jsonl"),
            "battle": center, "behaviour": {"walk_period_ms": 1500},
            "players": [{"token": token, "name": f"Feed{i}", "role": "walk"} for i, token in enumerate(tokens)],
            # The game client's perception set as shipped (cue_transport_on and near_tier_on on by
            # default: the tiers and the cue tables), in both arms.
            # and the copy tables (motion_tables_on, characters_table_on, on since bv-defaults-on).
            "client": "game", "feed": "legacy" if arm == "off" else "scoped", "tiers": True, "cues": True,
            "motion_tables": True, "character_tables": True,
        }))
        joined = client.expect("joined", 300)
        for player, (x, y) in zip(joined["players"], spots):
            call("place_at", player["id"], x, y)
        client.send("placed")
        client.expect("ready", 300)
        day_ms = sql("SELECT day_ms FROM world")[0]["day_ms"]
        noon = time.time_ns() // 1_000_000 - day_ms * 5 // 24
        harness("sql", f"UPDATE world SET epoch_ms = {noon} WHERE id = 0")
        client.send("go")
        go_at = time.time()
        time.sleep(5)
        harness("doctor")
        host_before = check_host()
        start_census = census()
        ident = battle.database_identity(db)
        if not ident:
            raise RuntimeError("could not resolve the database identity")
        m0 = battle.metrics(ident)
        first_stats = sql("SELECT ticks, at_ms FROM stats")[0]
        call("set_profile", True)
        start = time.time()
        fighter_counts = []
        try:
            for offset in range(5, seconds, 5):
                time.sleep(max(0, start + offset - time.time()))
                if fighters:
                    bodies = sql("SELECT id, x, y FROM body")
                    fighter_counts.append(sum(row["id"] in fighters and math.dist((row["x"], row["y"]), center) <= 16 for row in bodies))
            time.sleep(max(0, start + seconds - time.time()))
        finally:
            end = time.time()
            call("set_profile", False)
        last_stats = sql("SELECT ticks, at_ms FROM stats")[0]
        m1 = battle.metrics(ident)
        end_census = census()
        elapsed = end - start
        ticks_s = (last_stats["ticks"] - first_stats["ticks"]) * 1000 / (last_stats["at_ms"] - first_stats["at_ms"])
        # The server writes a busy module's log late (the woods' spans arrived tens of seconds after
        # the window, 2026-11-19): read it until the window's tick spans are all there.
        for _ in range(30):
            time.sleep(3)
            module_log(ident, evidence / "module-full.jsonl")
            spans, diags, periods = parse_log(evidence / "module-full.jsonl", start, end)
            ticks = spans.pop("tick", [])
            if abs(len(ticks) - ticks_s * elapsed) <= ticks_s * elapsed * 0.03:
                break
        popin = {"delays_ms": [], "dist_m": [], "missed_in_sight_ms": []}
        if arm == "probe":
            parse_log(evidence / "module-full.jsonl", go_at, end, popin)
        if merge_running():
            raise RuntimeError("a merge took ~/slop-mq/lock during the window")
        if not ticks or last_stats["ticks"] <= first_stats["ticks"] or client.p.poll() is not None:
            raise RuntimeError("missing tick samples or live SDK workload")
        if abs(len(ticks) - ticks_s * elapsed) > ticks_s * elapsed * 0.03:
            raise RuntimeError(f"{len(ticks)} tick spans vs {ticks_s * elapsed:.0f} ticks: the module log is incomplete")
        (evidence / "window.json").write_text(json.dumps({"unix_s": [start, end], "stats": [first_stats, last_stats], "metrics": [m0, m1], "host": [host_before, host()]}, indent=2) + "\n")
        actions = sql(f"SELECT COUNT(*) AS n FROM skill_use WHERE accepted_ms >= {int(start * 1000)} AND accepted_ms < {int(end * 1000)}")[0]["n"]
        # Non-overlapping sight spans only: `sight.gather` (sweep-exact) runs inside
        # `sight.player_candidates` and is kept apart, not summed.
        sight = {k: sum(v) / elapsed for k, v in spans.items() if k.startswith(("sight.", "scene.sensed")) and k not in NESTED}
        nested = {k: sum(v) / elapsed for k, v in spans.items() if k in NESTED}
        bytes_key, memory_key = "spacetime_num_bytes_sent_to_clients_total", "spacetime_worker_wasm_memory_bytes"
        if any(key not in data for data in (m0, m1) for key in (bytes_key, memory_key)):
            raise RuntimeError("missing required DB metrics")
        client.p.terminate()
        client.p.wait(timeout=30)
        feed_q = [f"SELECT * FROM {t}" for t in COMMON + FEEDS[arm]]
        reconnect = subprocess.run([binary, "feed-snapshot"], text=True, input=json.dumps({"uri": load.URL, "db": db, "token": tokens[0], "queries": feed_q}) + "\n", capture_output=True, check=True, timeout=60)
        per = max(periods, 1)
        result = dict(workload=workload, arm=arm, duration_s=elapsed, host_before=host_before, host_after=host(), load_wait=waited,
                      clients=count, ambient=ambient, census=[len(start_census), len(end_census)],
                      fighters=[sum(f in c for f in fighters) for c in (start_census, end_census)],
                      local_fighters_in_16m=fighter_counts, accepted_skill_uses_s=actions / elapsed,
                      sight_ms_s=sum(sight.values()), sight_spans_ms_s=sight, nested_spans_ms_s=nested,
                      tick_ms=statistics.mean(ticks), tick_samples=len(ticks), ticks_s=ticks_s,
                      late_share=sum(t > 16.7 for t in ticks) / len(ticks),
                      copy_writes_s=sum(v for k, v in diags.items() if k.startswith("scope:copy_")) / per,
                      memory_writes_s=sum(v for k, v in diags.items() if k.startswith("scope:memory_")) / per,
                      scope_tests_s=diags.get("scope:tests", 0) / per, diagnostic_seconds=periods,
                      loop={k.split(":")[1]: diags.get(k, 0) for k in ("scope:local", "scope:walk", "scope:loop_checked", "scope:loop_differed", "scope:far_skipped")},
                      total_kb_s_per_client=(m1[bytes_key] - m0[bytes_key]) / (1000 * elapsed * count),
                      reconnect=json.loads(reconnect.stdout), wasm_memory_bytes=[m0[memory_key], m1[memory_key]],
                      profile_source="full server module log", cpus=placement,
                      popin=dict(quantiles(popin["delays_ms"]), missed=len(popin["missed_in_sight_ms"]),
                                 missed_in_sight=quantiles(popin["missed_in_sight_ms"]), dist=quantiles([round(d) for d in popin["dist_m"]]),
                                 since_go_s=round(end - go_at, 1)) if arm == "probe" else None,
                      metrics_before=m0, metrics_after=m1)
        (evidence / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        if fighters and result["fighters"] != [96, 96]:
            raise RuntimeError("fighter census fell below 96")
        print(json.dumps({k: v for k, v in result.items() if not k.startswith("metrics_")}), flush=True)
        return result
    finally:
        if client and client.p.poll() is None:
            client.p.terminate()
            client.p.wait(timeout=30)
        if attempted:
            harness("cleanup")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--series", required=True, help="run-name prefix (letters, digits, hyphens)")
    p.add_argument("--workloads", default="middle:2,round:2,woods:4")
    p.add_argument("--woods-seed", type=lambda x: Path(x).resolve())
    p.add_argument("--seconds", type=int, default=30)
    p.add_argument("--max-load", type=float, default=6.0)
    p.add_argument("--probe-runs", type=int, default=1, help="probe arms per workload (pop-in delays; not a cost arm)")
    p.add_argument("--check-runs", type=int, default=1, help="loop-check arms per workload (exactness; not a cost arm)")
    p.add_argument("--stop-after", default="middle", help="stop when this workload, once done, misses the budget")
    p.add_argument("--reclaim-closed", action="store_true", help="the coordinator closed tonight's reclaim window before 02:00")
    a = p.parse_args()
    global RECLAIM_CLOSED
    RECLAIM_CLOSED = a.reclaim_closed
    if a.reclaim_closed:
        print("reclaim window closed early by the coordinator", flush=True)
    if load.CONTAINER == "sao-living_spacetimedb_1" or "3300" in load.URL:
        p.error("use a private server (LIVING_STDB_CONTAINER, LIVING_STDB_URL)")
    plan = [(w, int(n)) for w, n in (x.split(":") for x in a.workloads.split(","))]
    if any(w == "woods" for w, _ in plan) and not (a.woods_seed and a.woods_seed.is_file()):
        p.error("--woods-seed must point to the archived cover acceptance fixture JSON")
    out = ROOT / ".local/living/verify" / f"feedcost-{a.series}.jsonl"
    with (Path.home() / "slop-mq/battle.lock").open("r") as lock:
        print("waiting for the battle lock", flush=True)
        fcntl.flock(lock, fcntl.LOCK_EX)
        print("holding the battle lock", flush=True)
        for workload, repeats in plan:
            for index in range(1, repeats + 1):
                arms = ["off", "on"] + (["probe"] if index <= a.probe_runs else []) + (["check"] if index <= a.check_runs else [])
                for arm in arms:
                    for attempt in (1, 2):
                        if not in_window():
                            print("outside the measurement window: stopping", flush=True)
                            return 1
                        name = f"fc-{a.series}-{workload}-{index}-{arm}-a{attempt}"
                        print(f"START {name}", flush=True)
                        try:
                            r = one(name, workload, arm, a.seconds, a.woods_seed, a.max_load)
                        except Exception as exc:  # noqa: BLE001
                            print(f"FAILED {name}: {exc}", flush=True)
                            with out.open("a") as f:
                                f.write(json.dumps({"run": name, "failed": str(exc)}) + "\n")
                        else:
                            with out.open("a") as f:
                                f.write(json.dumps({"run": name, **{k: v for k, v in r.items() if not k.startswith("metrics_")}}) + "\n")
                            break
            if workload == a.stop_after:
                verdict = budget(out, workload)
                print(f"BUDGET {workload}: {json.dumps(verdict)}", flush=True)
                if not verdict.get("pass"):
                    print(f"{workload} misses the budget: stopping the series to report", flush=True)
                    return 2
    return 0


def budget(out, workload):
    """The standing rule (docs/COVER_SIGHT.md) for one workload of this series: worst on sight at
    most +15% over the off mean, ticks/s no lower than the lowest off, late share no higher than
    the highest off."""
    rows = [json.loads(l) for l in out.read_text().splitlines() if l.strip()] if out.exists() else []
    rows = [r for r in rows if "failed" not in r and r.get("workload") == workload]
    off = [r for r in rows if r["arm"] == "off"]
    on = [r for r in rows if r["arm"] == "on"]
    if len(off) < 2 or len(on) < 2:
        return {"pass": False, "why": f"{len(off)} off and {len(on)} on runs"}
    m = statistics.mean(r["sight_ms_s"] for r in off)
    worst = max(r["sight_ms_s"] for r in on) / m - 1
    ticks = min(r["ticks_s"] for r in on) >= min(r["ticks_s"] for r in off)
    late = max(r["late_share"] for r in on) <= max(r["late_share"] for r in off)
    return {"pass": worst <= 0.15 and ticks and late, "sight_vs_off_mean": round(worst, 4), "off_mean": round(m, 2), "ticks_ok": ticks, "late_ok": late}


if __name__ == "__main__":
    sys.exit(main())
