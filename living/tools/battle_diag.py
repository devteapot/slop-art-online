#!/usr/bin/env python3
"""Where a battle of minded fighters spends the authority's tick, over time (docs/BATTLE_SCALE.md).
Free: the fake model; scratch `verify-minds-*` databases on the trial stack.

  battle_diag.py --run minds-bd-<stamp> [--battle 100] [--walkers 116] [--minutes 30]
                 [--window 30] [--period 60] [--no-mind] [--fast-lane [--fast-real] [--fake-fast-patch]]
                 [--keep-plans] [--law NAME=VALUE] [--arm LABEL] [--no-refill] [--refill-from 30]
                 [--refill-gap 0.5] [--law NAME=VALUE ...] [--fixed-site X Y]
                 [--real-minds --allow-live [--concurrency 192] [--save-self]]

Seed `island` (its residents and animals on their own rules). `--battle` minded people
(`spawn_crowd`) packed onto seed-ordered walkable tiles near the arrival point fight the
nearest person: strike; dodge or block when threatened; heal below half (knowing
wound_tending). `--walkers` more walk as foragers. A fighter who dies is replaced (the load
generator's respawn, counted), unless `--no-refill`: deaths are then permanent, as in the game,
and the battle runs down. A refill appears `--refill-from` metres off (30) at a random bearing,
one at a time, at most one every `--refill-gap` seconds (0.5), walks into the battle and is given
the fight within 9 m of the site, so a battle's drift is the battle's, not the generator's. `--law` sets a world law after launch (`witness_fold_ms=0`
for the unfolded lines, `profile_detail=true` to time the parts of each evaluation). The mind service thinks for all of them on the fake
model (think 5 s, compile 4 s, consolidation 4 s, talk 2 s), its compile keeping the fight graph,
unless `--no-mind` (requests to think then stay pending, refreshed with their scene).
`--real-minds --allow-live` (paid: docs/INPUT_LATENCY.md, "Real-model trial") instead thinks for
the fighters and their refills with the real models config (living/configs/models.json, its
`people` mix as every fighter's default: think GLM 5.3 Flash; compile DeepSeek V4.1 Flash on stage,
GLM off stage), the key from the checkout's `.env` (read, never printed or logged); the walkers
then have no mind. Their compiles write their own graphs; the fight graph is only how they start.
Spend is not capped here: run `act_trial.py watch` beside it.
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
import concurrent.futures
import gzip
import importlib.util
import json
import math
import os
import random
import re
import signal
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import input_latency
from trial_activity import running_trial

from verify_steering import pose

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("privacy", ROOT / ".agents/skills/verify-minds/scripts/privacy.py")
pv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pv)
vm = pv.vm
STDB = str(ROOT / "living/tools/stdb")
URL = os.environ.get("LIVING_STDB_URL", "http://127.0.0.1:3300").rstrip("/")
TABLES = ["character", "experience", "structure", "skill_use", "deliberation", "familiar", "combat_seen", "chronicle", "thought",
          "mind_state", "far_handle", "act_outcome", "line_heard", "inventory", "body", "vitals", "routine", "slumber", "relation", "judgment"]


CONTACT_PERIOD_S = 1.0
AWAY_RADIUS_M = 15.0
REENGAGE_S = 10.0


def authority_token():
    result = subprocess.run([STDB, "login", "show", "--token"], capture_output=True, text=True,
                            check=True, timeout=20)
    match = re.search(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", result.stdout)
    if not match:
        raise RuntimeError("could not read the scratch database owner's token")
    return match[0]


def authority_sql(run, token, query):
    """Read an owner-only diagnostic projection without a CLI subprocess per sample."""
    request = urllib.request.Request(f"{URL}/v1/database/{run.db}/sql", data=query.encode(),
                                     headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=8) as response:
        result, = json.load(response)
    names = [element["name"]["some"] for element in result["schema"]["elements"]]
    return [dict(zip(names, row)) for row in result["rows"]]


def initial_formation(run, token, world, count, walkers, anchor=None):
    """Pick tile centres from the terrain, without depending on moving bodies or reducer RNG.
    The formation gathers round `anchor` (`--fixed-site`), or 20 m north of the arrival point."""
    width, height = world["width"], world["height"]
    if anchor is None:
        arrival, = run.private("SELECT arrive_x, arrive_y FROM land WHERE id = 0", "battle-arrival")
        anchor = (arrival["arrive_x"], arrival["arrive_y"] - 20)
    x0, y0 = map(math.floor, anchor)

    @lru_cache(maxsize=256)
    def chunk(cx, cy):
        row, = authority_sql(run, token, f"SELECT tiles FROM terrain_chunk WHERE id = {(cy << 16) | cx}")
        data = row["tiles"]
        return bytes.fromhex(data.removeprefix("0x")) if isinstance(data, str) else bytes(data)

    def walkable(x, y):
        return chunk(x // 16, y // 16)[(y % 16) * 16 + x % 16] in (0, 1, 3, 5, 6)

    candidates = [(x + 0.5, y + 0.5)
                  for y in range(max(0, y0 - 35), min(height, y0 + 36))
                  for x in range(max(0, x0 - 35), min(width, x0 + 36))
                  if walkable(x, y)]
    candidates.sort(key=lambda p: (math.dist(p, anchor), p))
    formation_size = max(200, count)
    if len(candidates) < formation_size:
        raise RuntimeError("too few walkable tiles for the initial battle formation")
    site = candidates[0]
    slots = candidates[:formation_size]
    rng = random.Random(world["seed"])
    rng.shuffle(slots)
    offsite = {}
    # A separate stream keeps walker positions unchanged across battle sizes.
    rng = random.Random(f"battle walkers {world['seed']}")
    for _ in range(walkers * 100):
        if len(offsite) == walkers:
            break
        x, y = rng.randrange(4, width - 4), rng.randrange(4, height - 4)
        point = (x + 0.5, y + 0.5)
        if math.dist(point, site) > 45 and walkable(x, y):
            offsite[point] = None
    if len(offsite) != walkers:
        raise RuntimeError("too few walkable tiles for the extra walkers")
    staging = next(p for p in candidates[formation_size:] if math.dist(p, site) >= 22)
    return site, slots, list(offsite), staging


def capture_combat(run, token, roster, stop, first_ms, path):
    """Save observations across the entire run, including gaps between profiling windows."""
    def query(sql):
        return authority_sql(run, token, sql)

    since = first_ms
    with gzip.open(path, "wt", compresslevel=3) as stream:
        while True:
            loop_start = time.monotonic()
            at_ms = time.time_ns() // 1_000_000
            try:
                bodies = query("SELECT id, x, y, vx, vy, t_ms, next_ms, heading, turn, turn_s FROM body")
                activities = query("SELECT id, skill, started_ms FROM activity")
                fighters = roster.copy()
                uses = query("SELECT id, actor, target, skill, accepted_ms, outcome, outcome_ms "
                             f"FROM skill_use WHERE accepted_ms >= {since} OR outcome_ms >= {since}")
                hurt = query("SELECT id, observer, at_ms, text FROM experience "
                             f"WHERE kind = 'attacked' AND at_ms >= {since}")
                # Bodies vanish at death. Roster entries persist for event attribution.
                sample = {"at_ms": at_ms, "fighters": fighters,
                          "bodies": [b for b in bodies if b["id"] in fighters],
                          "activities": [a for a in activities if a["id"] in fighters],
                          "uses": [u for u in uses if u["actor"] in fighters or u["target"] in fighters],
                          "hurt": [h for h in hurt if h["observer"] in fighters and ": " in h["text"]]}
                since = max(first_ms, at_ms - 2000)
            except (OSError, ValueError) as e:
                sample = {"at_ms": at_ms, "error": str(e)}
            stream.write(json.dumps(sample, separators=(",", ":")) + "\n")
            stream.flush()
            if stop.wait(max(0.0, CONTACT_PERIOD_S - (time.monotonic() - loop_start))):
                break


def interrupted(signum, _frame):
    raise KeyboardInterrupt(f"signal {signum}")


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


def patched(run):
    """Each character's first installed fast patch (ms): `thought` rows of kind `fast` that are
    neither kept nor refused."""
    first = {}
    for r in run.private("SELECT actor, kind, summary, at_ms FROM thought WHERE kind = 'fast'", "fast-patched"):
        if not str(r.get("summary", "")).startswith(("kept", "refused")):
            first[r["actor"]] = min(first.get(r["actor"], r["at_ms"]), r["at_ms"])
    return first


def defences(run, fighters, w0, w1, first_patch):
    """Blows and shots aimed at fighters whose windup began in [w0, w1), and the share met by the
    target's dodge, block or jump accepted between the windup's start and its release (+50 ms)."""
    uses = run.private(f"SELECT id, actor, skill, target, accepted_ms, released_ms FROM skill_use WHERE accepted_ms >= {int(w0) - 5000}", "skill-uses")
    by_actor = {}
    for u in uses:
        if u.get("accepted_ms"):
            by_actor.setdefault(u["actor"], []).append(u)
    out = {"blows": 0, "met": 0, "patched_blows": 0, "patched_met": 0}
    for u in uses:
        if u["skill"] not in ("strike", "attack", "bowshot", "shoot", "throw") or u.get("target") not in fighters or not u.get("accepted_ms"):
            continue
        if not (w0 <= u["accepted_ms"] < w1):
            continue
        end = (u.get("released_ms") or u["accepted_ms"] + 750) + 50
        met = any(d["skill"] in ("dodge", "block", "jump") and u["accepted_ms"] <= d["accepted_ms"] <= end for d in by_actor.get(u["target"], []))
        p = u["target"] in first_patch and first_patch[u["target"]] <= u["accepted_ms"]
        out["blows"] += 1
        out["met"] += met
        out["patched_blows"] += p
        out["patched_met"] += p and met
    out["share"] = round(out["met"] / out["blows"], 3) if out["blows"] else None
    out["patched_share"] = round(out["patched_met"] / out["patched_blows"], 3) if out["patched_blows"] else None
    return out


def count(run, table):
    out = subprocess.run([STDB, "sql", "-s", "local", run.db, f"SELECT COUNT(*) AS n FROM {table}"], capture_output=True, text=True).stdout
    nums = [l.strip() for l in out.splitlines() if l.strip().isdigit()]
    return int(nums[-1]) if nums else None


def database_identity(db):
    """A database's identity by its name (`GET /v1/database/<name>`); "" when it is gone. The
    server's `spacetime list` drops a database once deleted and is not a sampler's source."""
    try:
        with urllib.request.urlopen(f"{URL}/v1/database/{db}", timeout=30) as r:
            return json.loads(r.read())["database_identity"]["__identity__"].removeprefix("0x")
    except Exception:  # noqa: BLE001
        return ""


def metrics(ident, *, trace=False):
    # The last group is what this database sends its subscribers (cumulative; a window's rate is
    # the difference between samples): on a battle world the mind service is its one subscriber.
    want = ("spacetime_worker_wasm_memory_bytes", "spacetime_message_log_size_bytes", "spacetime_worker_instance_operation_queue_length", "spacetime_module_log_file_size_bytes",
            "spacetime_num_bytes_sent_to_clients_total", "spacetime_num_delta_queries_evaluated", "spacetime_num_delta_queries_matched", "spacetime_num_duplicate_rows_sent",
            "spacetime_subscription_query_execution_time_micros_sum", "spacetime_subscription_query_execution_time_micros_count",
            "spacetime_subscription_lock_wait_time_sec_sum", "spacetime_subscription_send_queue_length", "spacetime_subscription_connections")
    timed = (
        "spacetime_num_txns_total", "spacetime_reducer_plus_query_duration_sec", "spacetime_reducer_wait_time_sec", "spacetime_txn_elapsed_time_sec",
        "spacetime_total_outgoing_queue_length", "spacetime_total_incoming_queue_length",
        "spacetime_websocket_serialize_secs", "spacetime_websocket_sent_msg_size_bytes",
        "spacetime_websocket_sent_num_rows", "spacetime_websocket_pong_rtt_secs",
    )
    out = {}
    try:
        text = urllib.request.urlopen(f"{URL}/v1/metrics", timeout=3 if trace else 30).read().decode()
    except Exception as e:
        return {"error": str(e)}
    for line in text.splitlines():
        if line.startswith("#") or ident not in line:
            continue
        name = line.split("{", 1)[0]
        if trace and (name in want or name.startswith(timed + ("reducer_wasm_time_usec",))):
            key, value = line.rsplit(None, 1)
            out[key] = float(value)
            continue
        if name in ("spacetime_table_size_bytes", "spacetime_data_size_table_bytes_used_by_index_keys"):
            table = re.search(r'table_name="(familiar|seen_structures)"', line)
            if table:
                out[f"{name}:{table[1]}"] = int(float(line.rsplit(" ", 1)[1]))
            continue
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
    ap.add_argument("--fast-real", action="store_true",
                    help="with --fast-lane: fast calls go to the real `deepseek-flash` profile (living/configs/models.json, no overflow), every other purpose stays on the fake model; needs MISTRAL_API_KEY in the checkout's .env (read, never printed)")
    ap.add_argument("--keep-plans", action="store_true",
                    help="the fight is the fighter's one desire (its `combat` branch inside), and a fighter's compile answers \"keep\": a fast patch stays until the fighter's mind replaces it (all arms of a fast-lane comparison use it)")
    ap.add_argument("--fake-fast-patch", action="store_true",
                    help="with --fast-lane and the fake model: a fast call is answered with a `combat` patch (a dodge on a seen windup, then the fight) instead of keep, to prove patches install and persist for free")
    ap.add_argument("--arm", default="", help="a label for this run's arm, written into diag-head.json and every sample")
    ap.add_argument("--no-refill", action="store_true", help="deaths are permanent: the dead are not replaced, and the battle runs down")
    ap.add_argument("--refill-from", type=float, default=30.0,
                    help="a refill appears this far from the site (m), at a random bearing, and walks in before it fights")
    ap.add_argument("--refill-gap", type=float, default=0.5,
                    help="at most one refill every this many seconds: the dead are replaced one at a time, spread over time")
    ap.add_argument("--familiar", action="store_true",
                    help="read every character's `familiar` row count at each sample and once more before cleanup, by role "
                         "(fighter, walker, resident): familiar.json, familiar-<k>.json (docs/BATTLE_SCALE.md, note C2)")
    ap.add_argument("--fake-acts", default=None, metavar="JSON",
                    help="with the fake model: a fighter's compile also decides these deliberate acts (a JSON list of `do` nodes), as a model's may (docs/INPUT_LATENCY.md, \"Mind acts replace\")")
    ap.add_argument("--act-trace", action="store_true",
                    help="set the diagnostic law latency_acts and keep each deliberate act's course from the replica's module log in act-trace.jsonl (act_trace.py)")
    ap.add_argument("--law", action="append", default=[], metavar="NAME=VALUE",
                    help="set a world law after launch (JSON value), e.g. witness_fold_ms=0 or profile_detail=true")
    ap.add_argument("--input-latency", action="store_true",
                    help="record authority and mind timing plus database metrics for a fake-model fast-lane run")
    ap.add_argument("--real-minds", action="store_true",
                    help="paid: every fighter's mind (and each refill's) thinks with the real models config, `people` mix; walkers get no mind; needs --allow-live and MISTRAL_API_KEY in the checkout's .env")
    ap.add_argument("--allow-live", action="store_true", help="required with --real-minds, after authorization for this paid run")
    ap.add_argument("--fake-provider", action="store_true",
                    help="with --real-minds: the same models config (profiles, mixes, routing) with every profile sent to the local fake server (model `fake-<model>`, no key): the switch's free test")
    ap.add_argument("--concurrency", type=int, default=64, help="LIVING_CONCURRENCY for the mind service (the mind's own default is 192)")
    ap.add_argument("--save-self", action="store_true",
                    help="before cleanup, keep the fighters' `self` experiences (\"You keep turning back and forth\" lines) in self-lines.json")
    ap.add_argument("--fixed-site", nargs=2, type=float, metavar=("X", "Y"),
                    help="stage a fixed population in stationary, nonlethal fights round this point, for fake-model comparisons")
    a = ap.parse_args()
    if a.input_latency and (not a.fast_lane or a.fast_real or a.no_mind):
        ap.error("--input-latency requires --fast-lane with the fake model")
    if a.input_latency and not os.environ.get("CARGO_TARGET_DIR"):
        ap.error("--input-latency requires a private CARGO_TARGET_DIR")
    if a.real_minds and (not (a.allow_live or a.fake_provider) or a.no_mind or a.fast_real or a.fake_acts or a.fake_fast_patch or a.input_latency):
        ap.error("--real-minds needs --allow-live and excludes --no-mind, --fast-real, --fake-acts, --fake-fast-patch and --input-latency")
    fixed = a.fixed_site is not None
    if fixed and (not a.keep_plans or a.fast_real or a.no_mind or a.real_minds):
        ap.error("--fixed-site needs --keep-plans and a fake mind")
    if fixed:
        a.no_refill = True
    run = vm.Run(a.run)
    state = {"respawns": 0, "stop": False, "fighters": [], "arriving": {}}
    head = {}
    roster = {}
    stop_capture = threading.Event()
    sampler = keeper = None
    trace_start = time.time_ns() // 1_000_000
    metrics_stop = threading.Event()
    lat_sampler = None
    signal.signal(signal.SIGTERM, interrupted)
    try:
        target = os.environ.get("CARGO_TARGET_DIR")
        target_args = ["--target-dir", target] if target else []
        run.harness("launch", "--seed", "island", "--archive-commitlog",
                    "--driver-pid", str(os.getpid()), *target_args)
        token = authority_token()
        run.harness("doctor")
        run.admin("set_paused", True)
        if a.fast_lane:
            run.admin("set_world_law", "fast_lane_on", "true")
        if a.act_trace:
            run.admin("set_world_law", "latency_acts", "true")
        for law in a.law:
            name, value = law.split("=", 1)
            run.admin("set_world_law", name, value)
        # The database's identity by its name (`GET /v1/database/<name>`), not from `spacetime list`.
        ident = database_identity(run.db)
        if a.input_latency:
            run.admin("set_world_law", "latency_fast", "true")
            if not ident:
                raise RuntimeError("cannot identify the battle database for metrics")

            def sample_metrics():
                with (run.directory / "input-latency-metrics.jsonl").open("w") as out:
                    while not metrics_stop.is_set():
                        start = input_latency.epoch_ms()
                        values = metrics(ident, trace=True)
                        out.write(json.dumps({"start_ms": start, "end_ms": input_latency.epoch_ms(),
                                              "values": values}) + "\n")
                        out.flush()
                        metrics_stop.wait(max(0.0, 1.0 - (input_latency.epoch_ms() - start) / 1000))

            lat_sampler = threading.Thread(target=sample_metrics)
            lat_sampler.start()
        before = {c["id"] for c in run.sql("SELECT id FROM character", "chars-0")}
        # Keep the baseline roster export used by the earlier report.
        run.sql("SELECT id FROM character", "chars-probe")
        seed, = run.private("SELECT seed, width, height FROM world WHERE id = 0", "battle-seed")
        site, formation, walker_slots, staging = initial_formation(
            run, token, seed, a.battle, a.walkers, tuple(a.fixed_site) if fixed else None)
        if fixed:
            for law in ("dmg_strike", "dmg_strike_spear"):
                run.admin("set_world_law", law, "0.0")
        slots = formation[:a.battle]
        strike_card, = run.private("SELECT reach FROM skill_card WHERE skill = 'strike'", "battle-reach")
        if strike_card["reach"] <= 0:
            raise RuntimeError("strike has no positive reach in the installed rules")
        rng = random.Random(seed["seed"])
        fight_of = lambda id: [
            {"if": {"cond": {"health": {"below": 50}}, "then": {"do": {"skill": "heal", "target": "self"}}}},
            {"if": {"cond": {"threatened": True}, "then": {"do": {"skill": "dodge" if id % 2 == 0 else "block"}}}},
            {"do": {"skill": "strike", "target": {"nearest": "person"}}}]
        # --keep-plans: the fight is the fighter's one desire, its `combat` branch inside (the label
        # a fast patch replaces: rules graph.rs `patch_branch`). A person's top level is desires
        # (the mind keeps the body's needs among them), so a compile that answers "keep" leaves
        # it running; a bare fight graph would be rebuilt around the needs and the fight would stop.
        graph = (lambda id: {"desires": [{"want": "fight", "weight": {"base": 5.0}, "do": {"first": {"label": "combat", "children": fight_of(id)}}}]}) \
            if a.keep_plans else (lambda id: {"first": fight_of(id)})

        def spawn(n):
            have = {c["id"] for c in run.sql("SELECT id FROM character", "chars")}
            run.admin("spawn_crowd", n, True)
            # Only the ones spawned (a resident's child born meanwhile is new too).
            return sorted(c["id"] for c in run.sql("SELECT id, name, alive FROM character", "chars") if c["id"] not in have and c["name"].startswith("Walker") and c["alive"])

        def fighter(id, into, origin=None):
            """Set up a fighter: at the site, fighting; or (a refill) `--refill-from` away at a
            random bearing, walking to a spot in the battle, given the fight when it arrives."""
            run.admin("place_at", id, *(origin if origin else into))
            run.admin("grant_items", id, "spear", 1)
            run.admin("grant_know_how", id, "wound_tending")
            if origin:
                run.admin("set_behavior", id, json.dumps({"seq": [{"do": {"skill": "goto", "target": {"at": [into[0], into[1]]}}}, {"wait": 60}]}))
                state["arriving"][id] = into
            else:
                run.admin("set_behavior", id, json.dumps(graph(id)))

        def refill(id, into, origin):
            try:
                fighter(id, into, origin)
            except RuntimeError:
                # A refill can die during setup. The keeper will try a new fighter.
                pass

        made = spawn(a.battle + a.walkers)
        if len(made) != a.battle + a.walkers:
            raise RuntimeError(f"spawned only {len(made)} of {a.battle + a.walkers} initial walkers")
        fighters = made[:a.battle]
        # The authority snaps a placement if its tile is occupied. Clear the whole
        # formation, including slots unused by smaller arms, before placing anyone.
        all_slots = slots + walker_slots
        assigned = set(formation + walker_slots)
        ambient_moved = {}
        at_ms = time.time_ns() // 1_000_000
        before_formation = run.private(
            "SELECT id, x, y, vx, vy, t_ms, next_ms, heading, turn, turn_s FROM body",
            "before-formation")
        for body in before_formation:
            x, y = pose(body, at_ms)
            tile = (math.floor(x) + 0.5, math.floor(y) + 0.5)
            if tile in assigned:
                run.admin("place_at", body["id"], *staging)
                if body["id"] in before:
                    ambient_moved[body["id"]] = (x, y)
        for id, into in zip(fighters, slots):
            if fixed:
                run.admin("place_at", id, *into)
            else:
                fighter(id, into)
        for id, into in zip(made[a.battle:], walker_slots):
            run.admin("place_at", id, *into)
        bodies = {b["id"]: (b["x"], b["y"])
                  for b in run.private("SELECT id, x, y FROM body", "initial-bodies")}
        misplaced = [(id, into, bodies.get(id)) for id, into in zip(made, all_slots)
                     if bodies.get(id) != into]
        if misplaced:
            (run.directory / "misplaced.json").write_text(json.dumps(misplaced))
            raise RuntimeError("the authority could not place every spawned person in their seed-defined slot")
        walkers = set(made[a.battle:])
        state["ever_fighters"] = set(fighters)

        def bodies_at_site(label):
            alive = {c["id"] for c in run.sql("SELECT id, alive FROM character", f"fixed-alive-{label}") if c["alive"]}
            spots = {b["id"]: (b["x"], b["y"]) for b in
                     run.private("SELECT id, x, y FROM body", f"fixed-bodies-{label}")
                     if b["id"] in alive and b["id"] in fighters and math.dist((b["x"], b["y"]), site) <= 16}
            if len(spots) != a.battle:
                raise RuntimeError(f"fixed fixture {label}: {len(spots)} of {a.battle} fighters at the site")
            return spots

        if fixed:
            # Each fighter strikes its two nearest rivals within 1.6 m in turn, standing still;
            # strikes do no damage (the laws above), so the same 200 fight for the whole run.
            spots = bodies_at_site("start")
            (run.directory / "fixed-layout.json").write_text(json.dumps([spots[f] for f in fighters]))
            for fighter_id in fighters:
                neighbors = sorted((math.dist(spots[fighter_id], spot), other) for other, spot in spots.items()
                                   if other != fighter_id)
                rivals = [other for distance, other in neighbors if distance <= 1.6][:2]
                if not rivals:
                    raise RuntimeError(f"fixed fighter {fighter_id} has no opponent in strike range")
                strikes = []
                for other in rivals:
                    strikes.extend([{"do": {"skill": "strike", "target": {"id": other}}}, {"wait": 0.5}])
                run.admin("set_behavior", fighter_id, json.dumps({"desires": [
                    {"want": "fight", "weight": {"base": 5.0},
                     "do": {"seq": {"label": "combat", "children": strikes}}}
                ]}))
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
            # A fighter's compile reinstalls its fight; with --keep-plans it keeps the plan instead
            # ("graph": "keep", the mind's "carries on"), so an installed fast patch is not undone by
            # the next compile. A fixture of the fake model's script only.
            fight_reply = {"graph": "keep"} if a.keep_plans else {"graph": graph(0), "plan": "diag fixture: keep fighting", "weight": 1.5}
            if a.fake_acts:
                fight_reply = dict(fight_reply, acts=json.loads(a.fake_acts))
            fight = [{"purpose": "deliberate", "contains": f"# Who you are (Walker{n})", "delay_s": 4.0, "times": -1,
                      "reply": fight_reply} for n in range(1, a.battle + 1)]
            replies["fast"] = {"keep": True, "thought": "diag fixture: as it is."}
            if a.fake_fast_patch:
                replies["fast"] = {"patch": {"label": "combat", "graph": {"first": [
                    {"if": {"cond": {"doing": {"is": "hostile", "phase": "winding up", "at_me": True, "within": 3}}, "then": {"do": {"skill": "dodge"}}}}, *fight_of(0)]}},
                    "thought": "diag fixture: dodge their windup."}
            script = {"replies": replies, "rules": fight + [{"purpose": p, "delay_s": d, "times": -1, "reply": replies[p]} for p, d in (("think", 5.0), ("deliberate", 4.0), ("consolidate", 4.0), ("talk", 2.0), ("fast", 1.0))]}
            # The minds of everyone spawned, and of the fighters spawned later to refill the battle:
            # ids are handed out in order, so the next few thousand are theirs (an empty
            # LIVING_ONLY would mean no one).
            ids = list(made) if fixed else list(made) + list(range(max(made) + 1, max(made) + 4001))
            env = {"LIVING_CONCURRENCY": str(a.concurrency)}
            if a.real_minds:
                # Every purpose through the real models config, the `people` mix as the default; only
                # the fighters and the refills to come (not the walkers) are thought for.
                models = json.loads((ROOT / "living/configs/models.json").read_text())
                models["default"] = "people"
                keys = {p["key_env"] for p in models["profiles"].values()}
                if a.fake_provider:
                    fake = vm.model(run, script)["profiles"]["local"]
                    for name, p in models["profiles"].items():
                        models["profiles"][name] = dict(fake, model=f"fake-{p['model']}", **{k: p[k] for k in ("overflow", "capacity_overflow") if p.get(k)})
                    for k in keys:
                        env[k] = ""
                    keys = set()
                dotenv = {}
                if (ROOT / ".env").exists():
                    for line in (ROOT / ".env").read_text().splitlines():
                        k, eq, v = line.strip().partition("=")
                        if eq and k in keys:
                            dotenv[k] = v.strip().strip('"').strip("'")
                if not a.fake_provider and not dotenv.get("MISTRAL_API_KEY"):
                    raise RuntimeError("--real-minds needs MISTRAL_API_KEY in the checkout's .env")
                env.update({k: v for k, v in dotenv.items() if v})
                ids = [i for i in ids if i not in set(made[a.battle:])]
            else:
                models = vm.model(run, script)
            if a.input_latency:
                env["LIVING_INPUT_LATENCY"] = "1"
            if fixed:
                env["LIVING_BATTLE_TIMING"] = "1"
            if a.fast_real:
                # Only the fast route is real: rethink.json `fast.route` names `deepseek-flash`.
                real = json.loads((ROOT / "living/configs/models.json").read_text())["profiles"]["deepseek-flash"]
                real = {k: v for k, v in real.items() if k != "overflow"}
                key = next((l.split("=", 1)[1].strip().strip('"').strip("'") for l in (ROOT / ".env").read_text().splitlines()
                            if l.strip().startswith(real["key_env"] + "=")), "") if (ROOT / ".env").exists() else ""
                if not key:
                    raise RuntimeError(f"--fast-real needs {real['key_env']} in the checkout's .env")
                models["profiles"]["deepseek-flash"] = real
                env[real["key_env"]] = key
            (run.directory / "thinkers.json").write_text(json.dumps(ids))
            run.start(models, ids, seed="island", extra_env=env)

        def keep_battle():
            # Refills arrive one at a time, at most one each `--refill-gap` seconds, from
            # `--refill-from` away; each walks in and is given the fight within 9 m of the site
            # (before battle-loadgen, all the dead were replaced at once every 3 s, at the site).
            last = 0.0
            while not state["stop"]:
                try:
                    alive = {c["id"] for c in run.sql("SELECT id, alive FROM character", "alive") if c["alive"]}
                    dead = [f for f in state["fighters"] if f not in alive]
                    for f in dead:
                        state["fighters"].remove(f)
                    for f in [f for f in state["arriving"] if f not in alive]:
                        del state["arriving"][f]
                    state["deaths"] = state.get("deaths", 0) + len(dead)
                    if state["arriving"]:
                        at = {b["id"]: (b["x"], b["y"]) for b in run.private("SELECT id, x, y FROM body", "arriving")}
                        for f, into in list(state["arriving"].items()):
                            if f in at and math.dist(at[f], site) <= 9.0:
                                run.admin("set_behavior", f, json.dumps(graph(f)))
                                del state["arriving"][f]
                                state["fighters"].append(f)
                                roster[f] = time.time_ns() // 1_000_000
                    if a.input_latency:
                        with (run.directory / "input-latency-population.jsonl").open("a") as out:
                            out.write(json.dumps({"at_ms": input_latency.epoch_ms(),
                                                  "fighters": len(state["fighters"]),
                                                  "arriving": len(state["arriving"]),
                                                  "walkers_alive": len(walkers & alive)}) + "\n")
                    short = a.battle - len(state["fighters"]) - len(state["arriving"])
                    # As many as the time since the last refill allows, at most one each
                    # `--refill-gap` seconds: a loop of the keeper can take longer than the gap
                    # (its SQL under load), and one a loop then fell behind the deaths.
                    allowed = int((time.time() - last) / a.refill_gap) if last else 1
                    n = min(short, max(allowed, 0))
                    if n > 0 and not a.no_refill:
                        # Each refill's setup is four admin calls: in parallel, or they cap the
                        # refills below the deaths of a large battle.
                        ids = spawn(n)
                        state["ever_fighters"].update(ids)
                        setups = []
                        for id in ids:
                            into = (site[0] + rng.uniform(-7, 7), site[1] + rng.uniform(-7, 7))
                            bearing = rng.uniform(0, 2 * math.pi)
                            distance = a.refill_from + rng.uniform(-3, 3)
                            origin = (site[0] + distance * math.cos(bearing), site[1] + distance * math.sin(bearing))
                            setups.append((id, into, origin))
                        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                            list(pool.map(lambda setup: refill(*setup), setups))
                        state["respawns"] += len(ids)
                        last = time.time() if allowed <= n else last + n * a.refill_gap
                except Exception as e:
                    (run.directory / "keeper-error.txt").write_text(str(e))
                time.sleep(min(0.5, a.refill_gap))

        keeper = threading.Thread(target=keep_battle, daemon=True)
        head = {"arm": a.arm, "fast_real": a.fast_real, "real_minds": a.real_minds, "fake_provider": a.fake_provider, "concurrency": a.concurrency, "keep_plans": a.keep_plans, "fake_fast_patch": a.fake_fast_patch, "battle": a.battle, "walkers": a.walkers, "refill": not a.no_refill, "refill_from": a.refill_from, "refill_gap": a.refill_gap, "laws": a.law, "site": site, "ambient_at_publish": len(before), "mind": not a.no_mind, "fast_lane": a.fast_lane, "fake_acts": a.fake_acts, "act_trace": a.act_trace,
                "nproc": os.cpu_count(), "db_identity": ident, "world_seed": seed["seed"],
                "layout": [{"id": id, "at": bodies[id]} for id in fighters],
                "walker_layout": [{"id": id, "at": bodies[id]} for id in made[a.battle:]],
                "ambient_displaced": [{"id": id, "from": at, "to": bodies.get(id)}
                                      for id, at in ambient_moved.items()],
                "minutes": a.minutes, "combat_sampling": {"period_s": CONTACT_PERIOD_S, "away_radius_m": AWAY_RADIUS_M,
                    "reengage_s": REENGAGE_S, "strike_release_reach_m": strike_card["reach"]}}
        if a.input_latency:
            head["measurement_start_ms"] = input_latency.epoch_ms()
        (run.directory / "diag-head.json").write_text(json.dumps(head, indent=1))
        print(json.dumps(head), flush=True)
        first_ms = time.time_ns() // 1_000_000
        roster.update(dict.fromkeys(fighters, first_ms))
        head["started_ms"] = first_ms
        run.admin("set_paused", False)
        t_start, low, k = time.time(), 0, 0
        (run.directory / "measure-start-ms.txt").write_text(str(int(t_start * 1000)))
        first_over = {}

        def familiar_sample(label):
            """Each character's `familiar` rows by role, and by what they are of (structures,
            creatures, regions): the limit is 2,048 a character (brain.rs `FAMILIAR_LIMIT`)."""
            rows = run.private("SELECT actor, thing FROM familiar", f"familiar-{label}")
            alive = {c["id"]: c["alive"] for c in run.sql("SELECT id, alive FROM character", f"familiar-alive-{label}")}
            per, kinds = {}, {}
            for r in rows:
                per[r["actor"]] = per.get(r["actor"], 0) + 1
                kind = {1: "region", 2: "creature", 3: "structure"}.get(r["thing"] >> 40, "other")
                kinds.setdefault(r["actor"], {}).setdefault(kind, 0)
                kinds[r["actor"]][kind] += 1
            role = lambda x: "fighter" if x in state["ever_fighters"] else "walker" if x in walkers else "resident"
            t_min = round((time.time() - t_start) / 60, 2)
            for x, n in per.items():
                if n > 2048 and x not in first_over:
                    first_over[x] = {"t_min": t_min, "role": role(x), "rows": n}
            out = {"label": label, "t_min": t_min, "rows": len(rows), "first_over": first_over, "roles": {}}
            for rl in ("fighter", "walker", "resident"):
                ns = sorted(n for x, n in per.items() if role(x) == rl)
                live = sorted(n for x, n in per.items() if role(x) == rl and alive.get(x))
                q = lambda v, f: v[min(len(v) - 1, int(f * len(v)))] if v else 0
                out["roles"][rl] = {"actors": len(ns), "alive": len(live), "p50": q(ns, 0.5), "p90": q(ns, 0.9), "p99": q(ns, 0.99), "max": ns[-1] if ns else 0,
                                    "over_2048": sum(1 for n in ns if n > 2048), "max_alive": live[-1] if live else 0}
            top = sorted(per, key=lambda x: -per[x])[:20]
            out["top"] = [{"actor": x, "role": role(x), "alive": alive.get(x), "rows": per[x], "of": kinds.get(x, {})} for x in top]
            (run.directory / f"familiar-{label}.json").write_text(json.dumps({"summary": out, "per_actor": {str(x): [role(x), n] for x, n in per.items()}}) + "\n")
            with (run.directory / "familiar.json").open("a") as f:
                f.write(json.dumps(out) + "\n")
            return out
        sampler = threading.Thread(target=capture_combat, args=(run, token, roster, stop_capture, first_ms,
                                  run.directory / "combat-samples.jsonl.gz"))
        sampler.start()
        if not fixed:
            keeper.start()
        deadline = t_start + a.minutes * 60
        while time.time() < deadline:
            k += 1
            load0 = os.getloadavg()[0]
            window = min(a.window, max(1, int(deadline - time.time())))
            b, t0 = bench(run, f"{k:02d}", window)
            t1 = t0 + 1.2 + window
            d, secs = diag_counts(run, t0, t1 + 1)
            t, sp = b["tick_ms"], b["spans_ms"]
            sample = {"arm": a.arm, "k": k, "t_min": round((t0 - t_start) / 60, 1), "ticks_per_s": b["ticks_per_s"], "tick_p50": t["p50"], "tick_p99": t["p99"], "tick_max": t["max"],
                      "over_16_7": t["over_16_7ms"], "tick_samples": t["samples"], "spans_ms_s": {n: v["ms_per_s"] for n, v in sp.items() if v["ms_per_s"] >= 1.0},
                      "spans_n": {n: v["n"] for n, v in sp.items() if n.startswith(("perceive.", "brain."))}, "stats": {x: b.get(x) for x in ("evals_per_s", "experiences_per_s", "deliberation_requests_per_s", "motions_per_s")},
                      "diag_per_s": d, "diag_seconds": secs, "load_1m": [round(load0, 1), round(os.getloadavg()[0], 1)], "respawns": state["respawns"], "fighters_alive": len(state["fighters"]), "arriving": len(state["arriving"]), "fighter_deaths": state.get("deaths", 0)}
            if fixed:
                sample["fighters_alive"] = len(bodies_at_site(f"{k:02d}"))
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
                sample["fast"] = {"calls_in_window": sum(1 for x in fast if w0 <= x < w1), "per_s": round(sum(1 for x in fast if w0 <= x < w1) / window, 3),
                                  "total": len(fast), "fast_ask_rows": count(run, "fast_ask")}
            # Timed defences (R2's test, docs/COMBAT_MIND.md §4.2): each blow aimed at a fighter in
            # this window, and whether its target's dodge, block or jump began during the windup;
            # split by whether the target had a fast patch installed before the blow.
            sample["defence"] = defences(run, set(state["fighters"]), t0 * 1000, t1 * 1000, patched(run) if a.fast_lane else {})
            sample["metrics"] = metrics(ident) if ident else {}
            if a.familiar:
                try:
                    sample["rows"]["seen_structures"] = count(run, "seen_structures")
                    fs = familiar_sample(f"{k:02d}")
                    sample["familiar"] = {"rows": fs["rows"], "roles": fs["roles"], "over": len(fs["first_over"])}
                except Exception as e:
                    sample["familiar"] = {"error": str(e)[:200]}
            # How long remains lie (`rot` rows: when each is due, against when it was made) and how
            # many are left at the site; a death is permanent with --no-refill.
            try:
                built = {s_["id"]: s_ for s_ in run.private("SELECT id, kind, x, y, built_ms FROM structure", "structures") if s_["kind"] == "remains"}
                rot = run.private("SELECT structure, due_ms FROM rot", "rot")
                lasts = sorted(r["due_ms"] - built[r["structure"]]["built_ms"] for r in rot if r["structure"] in built)
                sample["remains"] = {"rows": len(built), "rot_rows": len(rot), "at_site": sum(1 for s_ in built.values() if (s_["x"] - site[0]) ** 2 + (s_["y"] - site[1]) ** 2 <= 30 ** 2),
                                     "lasts_ms_min": lasts[0] if lasts else None, "lasts_ms_max": lasts[-1] if lasts else None}
            except Exception as e:
                sample["remains"] = {"error": str(e)[:200]}
            with (run.directory / "diag.jsonl").open("a") as f:
                f.write(json.dumps(sample) + "\n")
            print(json.dumps({x: sample[x] for x in ("k", "t_min", "ticks_per_s", "tick_p50", "over_16_7", "alive", "respawns", "load_1m")} | {"exp_s": sample["stats"]["experiences_per_s"], "experience_rows": sample["rows"]["experience"]}), flush=True)
            low = low + 1 if b["ticks_per_s"] < 2 else 0
            if low >= 2:
                print("collapse: two windows below 2 ticks a second", flush=True)
                head["status"] = "collapse"
                break
            time.sleep(max(0, min(deadline, t0 + a.period) - time.time()))
        if fixed and "status" not in head:
            head["fighters_at_end"] = len(bodies_at_site("end"))
        head.setdefault("status", "done")
    except KeyboardInterrupt:
        head["status"] = "interrupted"
    except Exception as error:
        (run.directory / "failure.txt").write_text(traceback.format_exc())
        head["status"] = f"fail: {type(error).__name__}: {error}"
    finally:
        # Ignore repeated stop signals while the owner pauses and deletes the world.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        state["stop"] = True
        head["ended_ms"] = time.time_ns() // 1_000_000
        stop_capture.set()
        if run.mind and run.mind.poll() is None:
            run.mind.terminate()
        if "started_ms" in head:
            # Stop the tick before waiting for in-flight sampler or keeper queries. The
            # harness retries the pause and requires its read-back before deleting.
            req = urllib.request.Request(f"{URL}/v1/database/{run.db}/call/set_paused", data=b"[true]",
                                         headers={"Authorization": f"Bearer {token}",
                                                  "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=8):
                    pass
            except OSError:
                pass
        if sampler and sampler.ident is not None:
            sampler.join()
        if keeper and keeper.ident is not None:
            keeper.join()
        if a.input_latency:
            head["measurement_end_ms"] = input_latency.epoch_ms()
        metrics_stop.set()
        if lat_sampler:
            lat_sampler.join()
        if a.input_latency and "token" in locals():
            try:
                input_latency.capture_authority(URL, run.db, token,
                                                run.directory / "input-latency-authority.jsonl", trace_start)
            except (OSError, ValueError) as error:
                head["input_latency_capture_error"] = str(error)
        if a.save_self and "started_ms" in head:
            try:
                ever = state.get("ever_fighters", set())
                lines = [r for r in run.private("SELECT observer, at_ms, kind, text FROM experience WHERE kind = 'self'", "self-lines")
                         if r["observer"] in ever and r["at_ms"] >= head["started_ms"]]
                (run.directory / "self-lines.json").write_text(json.dumps(lines))
                head["self_lines"] = len(lines)
            except (OSError, ValueError, RuntimeError) as error:
                head["self_lines_error"] = str(error)
        if a.act_trace and "started_ms" in head:
            try:
                import act_trace
                container = os.environ.get("LIVING_STDB_CONTAINER", "sao-living_spacetimedb_1")
                head["act_trace_markers"] = act_trace.capture(container, act_trace.newest_replica(container),
                                                              run.directory / "act-trace.jsonl", trace_start)
                (run.directory / "fighters-ever.json").write_text(json.dumps(sorted(state.get("ever_fighters", []))))
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                head["act_trace_error"] = str(error)
        # The last read of `familiar`, before cleanup deletes the world.
        if a.familiar and "familiar_sample" in locals():
            try:
                familiar_sample("final")
            except Exception as e:
                (run.directory / "familiar-final-error.txt").write_text(str(e))
        (run.directory / "diag-result.json").write_text(json.dumps(head, indent=1))
        run.finish_cleanup()
        print(json.dumps(head), flush=True)
    return 0 if head.get("status") == "done" else 1


if __name__ == "__main__":
    with running_trial(os.environ.get("LIVING_STDB_CONTAINER")):
        sys.exit(main())
