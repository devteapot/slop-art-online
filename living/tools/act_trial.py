#!/usr/bin/env python3
"""The real-model trial of `mind_act_replaces` (docs/INPUT_LATENCY.md, "Real-model trial"): a live
spend guard, the town arms' sidecar sampler and the per-arm reports. Python standard library and
docker; reads the mind's own journals (llm.rs: one entry per model call, with its model and its
prompt, cached and completion tokens).

  act_trial.py watch --arm NAME --group town|battle --ledger FILE --log FILE --pid PID
                     --journal GLOB [--journal GLOB ...] --group-cap USD --total-cap USD
                     [--margin USD] [--price MODEL=IN,OUT,CACHED ...] [--interval 30]
                     [--url URL --container C --db DB --minds N] [--diag FILE --collapse-below TPS]
  act_trial.py town-side --instance DIR --url URL --container C [--bench-at MIN ...]
  act_trial.py report-town --instance DIR [--out FILE]
  act_trial.py report-battle --run-dir DIR [--skip-s 120] [--out FILE]
  act_trial.py ledger --ledger FILE

`watch` prices every journaled call from its tokens (`PRICES`, docs/MODEL_COST.md "Prices"; a
model it does not know is priced as the dearest known one and flagged), logs the arm's spend by
model every `--interval` seconds, and stops the arm's runner (SIGINT by PID, then SIGTERM after
180 s) at the first of:
- this arm's spend past min(group cap - the group's earlier arms, total cap - every earlier arm)
  minus `--margin` (calls already in flight when the stop lands);
- more than 10% of calls failing over the last 2 minutes (at least 20 calls);
- with `--diag` (battle_diag.py's samples): two windows in a row under `--collapse-below` ticks/s;
- with `--db` and `--minds-ids`: the thinkers' pending `deliberation` rows rising for 3 minutes (7
  samples, each at least the one before, the last above the first by 5 and by a tenth of `--minds`,
  and at least half of `--minds` waiting), after the arm's first 3.5 minutes;
- with `--container`: replacements (`act_replaced` markers in the newest replica's module log) above
  1 per mind-second over the last 60 s, twice in a row.
At its end the arm's final spend goes into `--ledger` (one entry per arm), which later arms read.

`town-side` follows one trials.py instance of the `act-town` trial: the thinkers' `activity` rows
every second (activities.jsonl.gz, as act_town.py samples them), `routine_stat` at the start and
after the run (the world is kept, `keep_db`), 30 s `bench.py` windows at `--bench-at` minutes, and
the replica's act markers (act-trace.jsonl, act_trace.py) once the instance is done.

The reports join the act markers with the journals: each batch a mind submitted (`act_submit`) is
matched to the journaled reply that decided it, so a batch decided while another of the mind's acts
ran (the overlap) can be compared with the act under way: "the same act again" is the same decided
act (`do`, target, item, amount, words, offer, pace: the JSON as the model wrote it, keys sorted),
the case `act_same_continues` would absorb.
"""
import argparse
import glob
import gzip
import json
import math
import os
import re
import signal
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import act_trace  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
# USD per million tokens: (input, output, cached input); docs/MODEL_COST.md "Prices" (Mistral, read
# 2026-11-09), as trials.py and gate_quality.py price them.
PRICES = {"deepseek-v4-1-flash-1017": (0.30, 1.20, 0.007), "zai-glm-5-3-flash": (0.15, 0.50, 0.03)}
DEAREST = (0.30, 1.20, 0.30)
REPLICAS = act_trace.REPLICAS


def now_ms():
    return time.time_ns() // 1_000_000


# ---- journals and money -----------------------------------------------------------------

class Journals:
    """Incremental reader of mind journals (one JSON line per model call)."""

    def __init__(self, patterns, prices):
        self.patterns = patterns
        self.prices = prices
        self.offsets = {}
        self.files = {}  # path -> {"entries": [(at_ms, model, purpose, prompt, cached, completion, error, latency, queue)]}

    def poll(self):
        for pat in self.patterns:
            for path in glob.glob(pat):
                try:
                    size = os.path.getsize(path)
                except OSError:
                    continue
                off = self.offsets.get(path, 0)
                if size <= off:
                    continue
                with open(path, "rb") as f:
                    f.seek(off)
                    data = f.read()
                end = data.rfind(b"\n") + 1
                self.offsets[path] = off + end
                rec = self.files.setdefault(path, [])
                for line in data[:end].splitlines():
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    if "purpose" not in e or e.get("purpose") == "rethink-gate":
                        continue
                    rec.append((e.get("at_ms") or 0, e.get("model") or "?", e["purpose"], e.get("prompt_tokens"), e.get("cached_tokens"),
                                e.get("completion_tokens"), bool(e.get("error")), e.get("latency_ms"), e.get("queue_wait_ms")))

    def entries(self):
        """Every call once: a journal copied elsewhere (the battle's cleanup copies it into the run's
        directory) is the same file by name; the longer copy counts."""
        best = {}
        for path, rec in self.files.items():
            name = os.path.basename(path)
            if name not in best or len(rec) > len(best[name]):
                best[name] = rec
        return [e for rec in best.values() for e in rec]

    def price(self, model):
        if model in self.prices:
            return self.prices[model], True
        if model.startswith("fake-"):
            return (0.0, 0.0, 0.0), True
        return DEAREST, False

    def spend(self, since_ms=None):
        by = defaultdict(lambda: Counter())
        unknown = set()
        for at, model, purpose, p, c, o, err, lat, q in self.entries():
            if since_ms is not None and at < since_ms:
                continue
            b = by[model]
            b["calls"] += 1
            b["errors"] += err
            b[f"calls:{purpose}"] += 1
            if p is None:
                continue
            (pin, pout, pcached), known = self.price(model)
            if not known:
                unknown.add(model)
            c = c or 0
            o = o or 0
            b["prompt_tokens"] += p
            b["cached_tokens"] += c
            b["completion_tokens"] += o
            b["usd_e6"] += (p - c) * pin + c * pcached + o * pout
        out = {m: {k: v for k, v in b.items() if k != "usd_e6"} | {"usd": round(b["usd_e6"] / 1e6, 4)} for m, b in by.items()}
        return out, round(sum(b["usd_e6"] for b in by.values()) / 1e6, 4), sorted(unknown)

    def window(self, ms):
        cut = now_ms() - ms
        es = [e for e in self.entries() if e[0] >= cut]
        return len(es), sum(e[6] for e in es)


def parse_prices(items):
    prices = dict(PRICES)
    for item in items or []:
        model, _, v = item.partition("=")
        i, o, c = (float(x) for x in v.split(","))
        prices[model] = (i, o, c)
    return prices


def ledger_read(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {"arms": []}


def ledger_write(path, arm, entry):
    led = ledger_read(path)
    led["arms"] = [a for a in led["arms"] if a["arm"] != arm] + [entry]
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(led, indent=1))
    tmp.replace(path)


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# ---- the authority, read for the guard ----------------------------------------------------

def admin_token(container):
    out = subprocess.run(["docker", "exec", container, "spacetime", "login", "show", "--token"],
                         capture_output=True, text=True, timeout=30).stdout
    m = re.findall(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", out)
    if len(m) != 1:
        raise RuntimeError("could not read one admin token from the container's CLI")
    return m[0]


def sql(url, db, token, query, timeout=10):
    req = urllib.request.Request(f"{url}/v1/database/{db}/sql", data=query.encode(),
                                 headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        result, = json.load(r)
    names = [e["name"]["some"] for e in result["schema"]["elements"]]
    return [dict(zip(names, row)) for row in result["rows"]]


def recent_markers(container, replica, stage, seconds, tail_bytes=40_000_000):
    """`stage` markers of the last `seconds` from the tail of the replica's newest module log."""
    d = f"{REPLICAS}/{replica}/module_logs"
    r = subprocess.run(["docker", "exec", container, "sh", "-c",
                        f"tail -c {tail_bytes} \"$(ls -1 {d}/* | sort | tail -n 1)\" | grep -F 'input_latency {stage} '"],
                       capture_output=True, timeout=120)
    cut = (time.time() - seconds) * 1e6
    n = 0
    for line in r.stdout.decode("utf-8", "replace").splitlines():
        try:
            if int(json.loads(line)["ts"]) >= cut:
                n += 1
        except (ValueError, KeyError):
            continue
    return n


# ---- watch -----------------------------------------------------------------------------

def cmd_watch(a):
    prices = parse_prices(a.price)
    j = Journals(a.journal, prices)
    led = ledger_read(a.ledger)
    prior = [x for x in led["arms"] if x["arm"] != a.arm]
    prior_total = sum(x["usd"] for x in prior)
    prior_group = sum(x["usd"] for x in prior if x["group"] == a.group)
    limit = min(a.group_cap - prior_group, a.total_cap - prior_total) - a.margin
    head = {"arm": a.arm, "group": a.group, "pid": a.pid, "started_ms": now_ms(), "prior_total_usd": round(prior_total, 4),
            "prior_group_usd": round(prior_group, 4), "group_cap": a.group_cap, "total_cap": a.total_cap, "margin": a.margin,
            "stop_at_usd": round(limit, 4), "prices": {m: list(v) for m, v in prices.items()}}
    log = open(a.log, "a")

    def write(rec):
        log.write(json.dumps(rec) + "\n")
        log.flush()

    write({"head": head})
    print(json.dumps(head), flush=True)
    if limit <= 0:
        reason = f"no budget left: limit {limit:.2f}"
        stop(a.pid, reason, write)
        ledger_write(a.ledger, a.arm, {"arm": a.arm, "group": a.group, "usd": 0.0, "status": "refused", "stop": reason})
        return 2
    token = None
    replica = None
    depth = []
    thrash_hits = 0
    low = 0
    seen_diag = 0
    reason = None
    stopped_at = None
    while True:
        t = now_ms()
        j.poll()
        by, usd, unknown = j.spend()
        n2, f2 = j.window(120_000)
        rec = {"t_ms": t, "usd": usd, "by_model": by, "calls_2min": n2, "errors_2min": f2}
        if unknown:
            rec["unknown_models_priced_dearest"] = unknown
        checks = []
        if a.db and a.url and a.container and a.minds_ids and os.path.exists(a.minds_ids):
            # Only the thinkers' requests: a character without a mind (the island's other
            # residents, the battle's walkers) keeps its request pending for good.
            try:
                token = token or admin_token(a.container)
                ids = set(json.loads(Path(a.minds_ids).read_text()))
                n = sum(1 for r in sql(a.url, a.db, token, "SELECT actor FROM deliberation") if r["actor"] in ids)
                depth.append(n)
                rec["deliberations_pending"] = n
                w = depth[-7:]
                grace = t - head["started_ms"] < 210_000
                if (not grace and len(w) == 7 and all(y >= x for x, y in zip(w, w[1:]))
                        and w[-1] - w[0] >= max(5, 0.1 * (a.minds or 0)) and w[-1] >= 0.5 * (a.minds or 0)):
                    checks.append(f"deliberation backlog rising for 3 min: {w}")
            except Exception as e:  # noqa: BLE001
                rec["deliberations_error"] = str(e)[:200]
        if a.container and a.minds:
            try:
                replica = replica or act_trace.newest_replica(a.container)
                k = recent_markers(a.container, replica, "act_replaced", 60)
                per = k / (a.minds * 60)
                rec["replaced_60s"] = k
                rec["replacements_per_mind_s_60s"] = round(per, 5)
                thrash_hits = thrash_hits + 1 if per > 1.0 else 0
                if thrash_hits >= 2:
                    checks.append(f"runaway thrashing: {per:.3f} replacements per mind-second over 60 s, twice")
            except Exception as e:  # noqa: BLE001
                rec["markers_error"] = str(e)[:200]
        if a.diag and a.collapse_below and os.path.exists(a.diag):
            lines = [json.loads(x) for x in Path(a.diag).read_text().splitlines() if x.strip()]
            for s in lines[seen_diag:]:
                low = low + 1 if s["ticks_per_s"] < a.collapse_below else 0
                rec.setdefault("ticks_per_s", []).append(s["ticks_per_s"])
            seen_diag = len(lines)
            if low >= 2:
                checks.append(f"battle collapse: two windows under {a.collapse_below} ticks/s")
        if usd > limit:
            checks.append(f"spend ${usd:.2f} past this arm's limit ${limit:.2f}")
        if n2 >= 20 and f2 / n2 > 0.10:
            checks.append(f"call failures {f2}/{n2} over 2 min")
        if checks and reason is None and alive(a.pid):
            reason = "; ".join(checks)
            stopped_at = time.time()
            rec["stop"] = reason
            write(rec)
            stop(a.pid, reason, write, wait=False)
        else:
            write(rec)
        print(f"[{time.strftime('%H:%M:%S')}] {a.arm}: ${usd:.3f} (limit ${limit:.2f}) calls_2min {n2} errors {f2}"
              + (f" pending {rec.get('deliberations_pending')}" if "deliberations_pending" in rec else "")
              + (f" STOP: {reason}" if reason else ""), flush=True)
        if stopped_at and alive(a.pid) and time.time() - stopped_at > 180:
            write({"t_ms": now_ms(), "escalate": "SIGTERM"})
            try:
                os.kill(a.pid, signal.SIGTERM)
            except OSError:
                pass
            stopped_at = time.time() + 1e9
        if not alive(a.pid):
            break
        time.sleep(a.interval)
    # The runner is gone: its journals are complete (copied or live); a last full read.
    time.sleep(2)
    j.poll()
    by, usd, unknown = j.spend()
    final = {"arm": a.arm, "group": a.group, "usd": usd, "by_model": by, "status": "stopped" if reason else "ended",
             "stop": reason, "ended_ms": now_ms(), "unknown_models": unknown}
    write({"final": final})
    ledger_write(a.ledger, a.arm, final)
    print(json.dumps({"final": {k: final[k] for k in ("arm", "usd", "status", "stop")}}), flush=True)
    return 0


def stop(pid, reason, write, wait=True):
    write({"t_ms": now_ms(), "sigint": pid, "reason": reason})
    print(f"STOP {pid}: {reason}", flush=True)
    try:
        os.kill(pid, signal.SIGINT)
    except OSError:
        return
    if wait:
        deadline = time.time() + 180
        while alive(pid) and time.time() < deadline:
            time.sleep(2)
        if alive(pid):
            os.kill(pid, signal.SIGTERM)


# ---- the town's sidecar -------------------------------------------------------------------

def cmd_town_side(a):
    inst = Path(a.instance)
    while not (inst / "state.json").exists():
        time.sleep(2)
    st = {}
    deadline = time.time() + 1800
    while time.time() < deadline:
        try:
            st = json.loads((inst / "state.json").read_text())
        except (OSError, ValueError):
            st = {}
        if (st.get("roles") or {}).get("subject") and st.get("t0"):
            break
        time.sleep(2)
    # trials.py names an instance's database `verify-trial-<batch>-<instance>`.
    db = f"verify-trial-{inst.parent.name}-{inst.name}"
    ids = list(st["roles"]["subject"])
    residents = set(ids)
    token = admin_token(a.container)
    side = inst / "side"
    side.mkdir(exist_ok=True)
    (side / "residents.json").write_text(json.dumps(ids))
    (side / "routine-stat-0.json").write_text(json.dumps(sql(a.url, db, token, "SELECT * FROM routine_stat", 60)))
    head = {"db": db, "residents": len(ids), "started_ms": now_ms(), "t0": st["t0"]}
    benches = sorted(a.bench_at or [])
    bench_out = []

    def bench(label):
        env = dict(os.environ, LIVING_STDB=str(ROOT / "living/tools/stdb"), LIVING_STDB_CONTAINER=a.container)
        out = side / f"bench-{label}.json"
        r = subprocess.run([sys.executable, str(ROOT / "living/tools/bench.py"), "--db", db, "--seconds", "30", "--settle", "0",
                            "--log-lines", "930000", "--out", str(out)], cwd=ROOT, env=env, capture_output=True, text=True)
        (side / f"bench-{label}.log").write_text(r.stdout + r.stderr)
        if r.returncode == 0:
            b = json.loads(out.read_text())
            bench_out.append({"label": label, "load_1m": os.getloadavg()[0], "ticks_per_s": b["ticks_per_s"],
                              "tick_p50": b["tick_ms"]["p50"], "tick_p99": b["tick_ms"]["p99"]})

    with gzip.open(side / "activities.jsonl.gz", "wt", compresslevel=3) as out:
        while True:
            try:
                st = json.loads((inst / "state.json").read_text())
            except (OSError, ValueError):
                pass
            if st.get("status") in ("collecting", "done", "failed", "failed-keep") or st.get("stopped_by"):
                break
            at = now_ms()
            try:
                acts = sql(a.url, db, token, "SELECT id, skill, phase, node, started_ms, ends_ms FROM activity")
                out.write(json.dumps({"at_ms": at, "activities": [x for x in acts if x["id"] in residents]}, separators=(",", ":")) + "\n")
            except (OSError, ValueError) as e:
                out.write(json.dumps({"at_ms": at, "error": str(e)}) + "\n")
            if benches and time.time() - st.get("t0", time.time()) >= benches[0] * 60:
                label = f"m{benches.pop(0):g}"
                threading.Thread(target=bench, args=(label,), daemon=True).start()
            time.sleep(max(0.0, 1.0 - (now_ms() - at) / 1000))
    head["ended_ms"] = now_ms()
    # The instance pauses and keeps its world (`keep_db`); wait for its summary.
    deadline = time.time() + 600
    while not (inst / "summary.json").exists() and time.time() < deadline:
        time.sleep(2)
    try:
        (side / "routine-stat-1.json").write_text(json.dumps(sql(a.url, db, token, "SELECT * FROM routine_stat", 60)))
        (side / "routines.json").write_text(json.dumps(sql(a.url, db, token, "SELECT id, actor FROM routine", 60)))
        (side / "self-lines.json").write_text(json.dumps([r for r in sql(a.url, db, token, "SELECT observer, at_ms, kind, text FROM experience WHERE kind = 'self'", 60)
                                                          if r["observer"] in residents]))
        (side / "characters.json").write_text(json.dumps(sql(a.url, db, token, "SELECT id, name, alive FROM character", 60)))
        (side / "laws.json").write_text(json.dumps(sql(a.url, db, token, "SELECT * FROM law_override", 60)))
    except Exception as e:  # noqa: BLE001
        head["read_error"] = str(e)[:300]
    try:
        summary = json.loads((inst / "summary.json").read_text())
        replica = summary.get("replica") or act_trace.newest_replica(a.container)
    except (OSError, ValueError):
        replica = act_trace.newest_replica(a.container)
    head["replica"] = replica
    head["act_trace_markers"] = act_trace.capture(a.container, replica, side / "act-trace.jsonl", head["started_ms"] - 600_000)
    head["benches"] = bench_out
    (side / "side-head.json").write_text(json.dumps(head, indent=1))
    print(json.dumps(head), flush=True)
    return 0


# ---- reports ----------------------------------------------------------------------------

def strip_fences(text):
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.rsplit("```", 1)[0]
    s, e = t.find("{"), t.rfind("}")
    return t[s:e + 1] if s >= 0 and e > s else t


def act_skill(v):
    d = v.get("do")
    if isinstance(d, str):
        return d
    if isinstance(d, dict):
        return d.get("skill")
    return v.get("skill")


def canon(v):
    return json.dumps(v, sort_keys=True, separators=(",", ":"))


def decisions(journal_dirs):
    """Each journaled reply that decided acts: journal file name (llm.rs: the actor's name with every
    character that is not a letter or digit as `_`) -> [(at_ms, purpose, [act dicts, gaze left out])]."""
    out = defaultdict(list)
    seen = set()
    for d in journal_dirs:
        for path in sorted(Path(d).glob("*.jsonl")):
            if path.name in seen:
                continue
            seen.add(path.name)
            with open(path) as f:
                for line in f:
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    if not e.get("reply") or e.get("purpose") in ("rethink-gate", "consolidate", "reorganize", "internalize"):
                        continue
                    try:
                        r = json.loads(strip_fences(e["reply"]))
                    except ValueError:
                        continue
                    acts = r.get("acts") if isinstance(r, dict) else None
                    if not isinstance(acts, list) or not acts:
                        continue
                    acts = [x for x in acts if isinstance(x, dict) and x.get("do") != "gaze"]
                    if acts:
                        out[path.stem].append((e.get("at_ms") or 0, e["purpose"], acts))
    for v in out.values():
        v.sort(key=lambda x: x[0])
    return out


def overlaps(trace, names, decided, actors, from_ms=None, to_ms=None):
    """Batches decided while another of the mind's acts ran, and whether the batch's first act is
    the act under way again. `names`: actor id -> journal name (as llm.rs names the file)."""
    rows = sorted(act_trace.marks(trace), key=lambda m: (m["wall_ms"], m["reducer_us"]))
    if actors is not None:
        rows = [m for m in rows if m["actor"] in actors]
    used = set()
    running = {}       # actor -> {"skill", "canon", "start_ms"}
    queued = {}        # queue id -> canon
    batch_of = {}      # actor -> remaining decided acts of the batch being queued
    replaced_times = defaultdict(list)
    out = Counter()
    same_examples = []
    ages = []
    for m in rows:
        a, st = m["actor"], m["stage"]
        inside = (from_ms is None or m["wall_ms"] >= from_ms) and (to_ms is None or m["wall_ms"] <= to_ms)
        if st == "act_submit":
            source = m["detail"][0] if m["detail"] else "?"
            name = names.get(a)
            match = None
            for k, (at, purpose, acts) in enumerate(decided.get(name, [])):
                if (name, k) in used:
                    continue
                if m["wall_ms"] - 15_000 <= at <= m["wall_ms"] + 1_000:
                    match = (k, at, purpose, acts)
                if at > m["wall_ms"] + 1_000:
                    break
            if match:
                used.add((name, match[0]))
                batch_of[a] = list(match[3])
            else:
                batch_of[a] = []
            if not inside:
                continue
            out["submits"] += 1
            out[f"submits_from:{source}"] += 1
            out["submits_matched_to_a_reply"] += bool(match)
            cur = running.get(a)
            if cur is None:
                continue
            out["submits_while_an_act_ran"] += 1
            ages.append(m["wall_ms"] - cur["start_ms"])
            first = batch_of[a][0] if batch_of[a] else None
            if first is None:
                out["overlap_unmatched"] += 1
                continue
            same_skill = act_skill(first) == cur["skill"]
            same = cur["canon"] is not None and canon(first) == cur["canon"]
            out["overlap_same_skill"] += same_skill
            out["overlap_same_act"] += same
            if same and len(same_examples) < 12:
                same_examples.append({"actor": a, "name": names.get(a), "act": first, "age_ms": round(m["wall_ms"] - cur["start_ms"]), "source": source})
        elif st == "act_queued":
            skill = m["detail"][1] if len(m["detail"]) > 1 else None
            rest = batch_of.get(a, [])
            pick = next((i for i, x in enumerate(rest) if act_skill(x) == skill), None)
            queued[m["key"]] = canon(rest.pop(pick)) if pick is not None else None
        elif st == "act_started":
            running[a] = {"skill": m["detail"][0] if m["detail"] else "?", "canon": queued.pop(m["key"], None), "start_ms": m["wall_ms"]}
        elif st == "act_continued":
            queued.pop(m["key"], None)
            if inside:
                out["continued_by_the_same"] += 1
        elif st in ("act_refused", "act_expired"):
            queued.pop(m["key"], None)
        elif st == "act_replaced":
            running.pop(a, None)
            if inside:
                replaced_times[a].append(m["wall_ms"])
                if int(m["detail"][2]) < 3000:
                    out["replaced_within_3s_of_start"] += 1
        elif st == "act_done":
            running.pop(a, None)
    runs = 0
    for a, ts in replaced_times.items():
        k = 0
        while k + 2 < len(ts):
            if ts[k + 2] - ts[k] <= 20_000:
                runs += 1
                k += 3
            else:
                k += 1
    out["runs_of_3_replacements_within_20s"] = runs
    res = dict(out)
    s = out["submits"]
    o = out["submits_while_an_act_ran"]
    res["overlap_rate"] = round(o / s, 4) if s else None
    res["same_act_share_of_overlaps"] = round(out["overlap_same_act"] / o, 4) if o else None
    res["same_act_share_of_submits"] = round(out["overlap_same_act"] / s, 4) if s else None
    res["age_of_act_under_way_at_overlap_ms"] = act_trace.dist(ages)
    res["same_act_examples"] = same_examples
    return res


def money(journal_dirs, from_ms=None, to_ms=None):
    j = Journals([str(Path(d) / "*.jsonl") for d in journal_dirs], dict(PRICES))
    j.poll()
    es = [e for e in j.entries() if (from_ms is None or e[0] >= from_ms) and (to_ms is None or e[0] <= to_ms)]
    by, usd, unknown = j.spend()
    lat = defaultdict(list)
    q = defaultdict(list)
    for at, model, purpose, p, c, o, err, latency, wait in j.entries():
        if latency is not None and not err:
            lat[purpose].append(latency)
        if wait is not None:
            q[purpose].append(wait)
    return {"usd": usd, "by_model": by, "unknown_models": unknown, "calls": len(j.entries()),
            "errors": sum(e[6] for e in j.entries()), "calls_in_window": len(es),
            "latency_ms_by_purpose": {k: act_trace.dist(v) for k, v in lat.items()},
            "queue_wait_ms_by_purpose": {k: act_trace.dist(v) for k, v in q.items()}}


def journal_name(name):
    return "".join(ch if ch.isalnum() else "_" for ch in name)


def cmd_report_town(a):
    inst = Path(a.instance)
    side = inst / "side"
    sh = json.loads((side / "side-head.json").read_text())
    summary = json.loads((inst / "summary.json").read_text())
    ids = json.loads((side / "residents.json").read_text())
    residents = set(ids)
    chars = {c["id"]: c for c in json.loads((side / "characters.json").read_text())}
    names = {i: journal_name(chars[i]["name"]) for i in ids if i in chars}
    t0 = int(sh["t0"] * 1000)
    t1 = sh["ended_ms"]
    seconds = (t1 - t0) / 1000
    trace = side / "act-trace.jsonl"
    acts = act_trace.report(trace, residents, seconds, t0, t1)
    jdirs = [inst / "journal"]
    import act_town
    activity = act_town.tasks(side / "activities.jsonl.gz", residents)
    hours = seconds / 3600
    gather = activity["by_skill"].get("graph:gather", {})
    r0 = {r["id"]: r for r in json.loads((side / "routine-stat-0.json").read_text())}
    mine = {r["id"] for r in json.loads((side / "routines.json").read_text()) if r["actor"] in residents}
    delta = Counter()
    for r in json.loads((side / "routine-stat-1.json").read_text()):
        if r["id"] in mine:
            b = r0.get(r["id"], {"ok": 0, "failed": 0})
            delta["ok"] += r["ok"] - b["ok"]
            delta["failed"] += r["failed"] - b["failed"]
    selfs = [r for r in json.loads((side / "self-lines.json").read_text()) if "turning back and forth" in r["text"] and t0 <= r["at_ms"] <= t1]
    out = {"instance": str(inst), "variant": summary.get("variant"), "stopped_by": summary.get("stopped_by"),
           "world_laws": summary.get("world_laws"), "residents": len(ids), "seconds": round(seconds, 1),
           "money": money(jdirs, t0, t1),
           "acts": acts,
           "overlap": overlaps(trace, names, decisions(jdirs), residents, t0, t1),
           "turning_back_lines": len(selfs), "turning_back_per_mind_hour": round(len(selfs) / (len(ids) * hours), 4) if hours else None,
           "routine_outcomes": dict(delta), "activity_tasks": activity["tasks"],
           "graph_work": {k: v for k, v in activity["by_skill"].items() if k.startswith("graph:") and not any(k.endswith(x) for x in ("goto", "wander", "step_aside", "follow"))},
           "act_work": {k: v for k, v in activity["by_skill"].items() if k.startswith("act:")},
           "gathers_done_per_resident_hour": round(gather.get("done", 0) / (len(ids) * hours), 2) if hours else None,
           "benches": sh.get("benches"),
           "deaths": sum(1 for i in ids if i in chars and not chars[i]["alive"])}
    text = json.dumps(out, indent=1)
    if a.out:
        Path(a.out).write_text(text)
    print(text)
    return 0


def cmd_report_battle(a):
    d = Path(a.run_dir)
    head = json.loads((d / "diag-result.json").read_text())
    diag = [json.loads(x) for x in (d / "diag.jsonl").read_text().splitlines() if x.strip()]
    fighters = set(json.loads((d / "fighters-ever.json").read_text()))
    t0 = head["started_ms"] + a.skip_s * 1000
    t1 = head["ended_ms"]
    seconds = (t1 - t0) / 1000
    trace = d / "act-trace.jsonl"
    acts = act_trace.report(trace, fighters, seconds, t0, t1)
    # Fighters in the measured window, by mean alive count (refills come and go).
    measured = [x for x in diag if x["t_min"] * 60 >= a.skip_s]
    alive = [x["fighters_alive"] for x in measured] or [x["fighters_alive"] for x in diag]
    minds = statistics.mean(alive) if alive else len(fighters)
    chars = {}
    chars_path = sorted(d.glob("chars*.json"))
    import flb_report
    cs = flb_report.combat_samples(d, head)
    t = cs.get("totals", {})
    names = {}
    # Fighter names from the run's saved character reads (the harness saves each SQL read).
    for p in sorted(d.glob("*.json")):
        if p.name.startswith(("chars", "alive", "census")):
            try:
                for c in json.loads(p.read_text()):
                    if isinstance(c, dict) and "id" in c and "name" in c:
                        chars[c["id"]] = c["name"]
            except (ValueError, TypeError):
                pass
    names = {i: journal_name(chars[i]) for i in fighters if i in chars}
    jdirs = [d / "journal"]
    selfs = []
    if (d / "self-lines.json").exists():
        selfs = [r for r in json.loads((d / "self-lines.json").read_text()) if "turning back and forth" in r["text"] and t0 <= r["at_ms"] <= t1]
    uses = Counter()
    final = {}
    with gzip.open(d / "combat-samples.jsonl.gz", "rt") as f:
        for line in f:
            s = json.loads(line)
            for u in s.get("uses", []):
                if u["actor"] in fighters and (u.get("accepted_ms") or 0) >= t0:
                    final[u["id"]] = u
    for u in final.values():
        o = u.get("outcome") or ""
        kind = next((k for k, rx in OUTCOME if rx.search(o)), "open" if not o else "other")
        uses[kind] += 1
    out = {"run": str(d), "arm": head.get("arm"), "status": head.get("status"), "laws": head.get("laws"), "seconds_measured": round(seconds, 1),
           "fighters_alive_mean": round(minds, 1), "fighters_alive_min": min(alive) if alive else None,
           "money": money(jdirs, t0, t1), "money_whole_run": money(jdirs),
           "acts": acts,
           "overlap": overlaps(trace, names, decisions(jdirs), fighters, t0, t1),
           "replacements_per_mind_second": round(acts["fate_of_started"].get("replaced", 0) / (minds * seconds), 6) if minds and seconds else None,
           "turning_back_lines": len(selfs), "turning_back_per_mind_hour": round(len(selfs) / (minds * seconds / 3600), 4) if minds and seconds else None,
           "combat_uses": dict(uses),
           "timed_defence": [x["defence"].get("share") for x in measured],
           "contact_share": cs.get("observed_time_shares", {}).get("contact"),
           "engagements_per_fighter_min": cs.get("per_fighter_minute", {}).get("engagements_started"),
           "contact_s_per_engagement": (t["contact_seconds"] / t["engagements_started"]) if t.get("engagements_started") else None,
           "attacks_per_contact_min": cs.get("attacks_per_contact_minute"),
           "ticks_per_s": [x["ticks_per_s"] for x in diag], "tick_p50": [x["tick_p50"] for x in diag], "tick_p99": [x["tick_p99"] for x in diag],
           "load_1m": [x["load_1m"] for x in diag], "deaths": diag[-1].get("fighter_deaths") if diag else None,
           "respawns": diag[-1].get("respawns") if diag else None}
    text = json.dumps(out, indent=1)
    if a.out:
        Path(a.out).write_text(text)
    print(text)
    return 0


OUTCOME = [("hit", re.compile(r"^hit for")), ("blocked", re.compile(r"^blocked")), ("dodged", re.compile(r"dodged")),
           ("missed", re.compile(r"miss")), ("broken_off", re.compile(r"^broken off")), ("refused", re.compile(r"^refused")),
           ("killed", re.compile(r"^killed")), ("healed", re.compile(r"^healed")), ("made_way", re.compile(r"^made way")),
           ("failed", re.compile(r"^failed"))]


def cmd_ledger(a):
    led = ledger_read(a.ledger)
    total = sum(x["usd"] for x in led["arms"])
    groups = Counter()
    for x in led["arms"]:
        groups[x["group"]] += x["usd"]
    print(json.dumps({"total_usd": round(total, 4), "by_group": {k: round(v, 4) for k, v in groups.items()},
                      "arms": [{k: x.get(k) for k in ("arm", "group", "usd", "status", "stop")} for x in led["arms"]]}, indent=1))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("watch")
    s.add_argument("--arm", required=True)
    s.add_argument("--group", required=True)
    s.add_argument("--ledger", required=True)
    s.add_argument("--log", required=True)
    s.add_argument("--pid", type=int, required=True)
    s.add_argument("--journal", action="append", required=True)
    s.add_argument("--group-cap", type=float, required=True)
    s.add_argument("--total-cap", type=float, required=True)
    s.add_argument("--margin", type=float, default=0.5)
    s.add_argument("--price", action="append", default=[])
    s.add_argument("--interval", type=float, default=30)
    s.add_argument("--url")
    s.add_argument("--container")
    s.add_argument("--db")
    s.add_argument("--minds", type=int)
    s.add_argument("--minds-ids", help="a JSON list of the thinkers' ids (the backlog counts only theirs)")
    s.add_argument("--diag")
    s.add_argument("--collapse-below", type=float)
    s = sub.add_parser("town-side")
    s.add_argument("--instance", required=True)
    s.add_argument("--url", required=True)
    s.add_argument("--container", required=True)
    s.add_argument("--bench-at", type=float, action="append")
    s = sub.add_parser("report-town")
    s.add_argument("--instance", required=True)
    s.add_argument("--out")
    s = sub.add_parser("report-battle")
    s.add_argument("--run-dir", required=True)
    s.add_argument("--skip-s", type=float, default=120)
    s.add_argument("--out")
    s = sub.add_parser("ledger")
    s.add_argument("--ledger", required=True)
    a = ap.parse_args()
    return {"watch": cmd_watch, "town-side": cmd_town_side, "report-town": cmd_report_town,
            "report-battle": cmd_report_battle, "ledger": cmd_ledger}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
