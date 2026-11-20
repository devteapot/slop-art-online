#!/usr/bin/env python3
"""Ticks a second in a 200-fighter battle by the number of player viewers in it (frame-views,
docs/TICK_RATE.md): whether a dense battle's cost is the players' frames and views.

    battle_viewers.py --label NAME --wasm FILE --load GATE_LOAD --viewers 0,1,4,16
                      [--fighters 200] [--seconds 60] [--warmup 20] [--tiers] [--cues] [--motion-tables] [--law NAME=VALUE]

For each count: publish fresh as `verify-lookcost-<label>-v<count>-<stamp>` on the worker's own
server (`LIVING_STDB_CONTAINER`, `LIVING_STDB_URL`, as look_cost.py), stage the battle with the
admin's `spawn_battle` (AI fighters within 7 m of the arrival less 20 m, a fight graph: attack the
nearest person, dodge or block when threatened), join that many players over their own WebSocket
connections (gate-load, the gate's subscriptions; `--tiers`/`--cues` as look_cost.py) and stand
them within 6 m of the battle's centre, walking small circles; after the warm-up, the tick count
of the server's own counter over the window. Writes `<out>/battle-viewers.json`. Delete each
database after. Python standard library.

With `--detail` (battle-views), each count's window is also profiled as tick_cost.py does, in
`<out>/v<count>/`: `metrics.json` (the database's server series before, after and their
difference), `threads.json`, `ticks.json` (each tick from its `Timing span "tick"`), `result.json`
and `module.log`, so `tick_report.py` reads it as a tick_cost run. With `--flip-off` (a run with
`motion_tables_on=true`), after the window the law goes off with profiling on and
`<out>/v<count>/flip-off.json` records the kill switch's one tick: the copies moved, its
`tick.motion_private` and `tick` spans, and the tick gaps (slots of 16.7 ms) 2 s before and 4 s
after it.

Also (combat-phase, docs/COMBAT_PHASE.md): `--detail` writes `load.log` (the host's 1-minute load
and MemAvailable every second of the window, as tick_report.py reads it). `--no-profile` keeps
`--detail`'s server metrics and thread CPU but leaves profiling off, so the window carries no span
logging (the uninstrumented cost). `--full-log` reads the replica's whole module log from the
server's data directory instead of the CLI's tail, which drops lines when detail spans log tens
of thousands a second; `span_report.py` reads it.
"""
import argparse
import json
import math
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import look_cost as lc  # noqa: E402
import tick_cost as tc  # noqa: E402


def tick_count(ident):
    text = urllib.request.urlopen(f"{lc.URL}/v1/metrics", timeout=60).read().decode()
    for line in text.splitlines():
        if line.startswith("spacetime_reducer_plus_query_duration_sec_count{") and f'"{ident}"' in line and 'reducer="tick"' in line:
            return float(line.rsplit(" ", 1)[1])
    return None


class LoadLog(threading.Thread):
    """Every second: the wall time, the host's 1-minute load and MemAvailable (GiB)."""

    def __init__(self, path):
        super().__init__(daemon=True)
        self.path, self.stop = path, threading.Event()

    def run(self):
        with open(self.path, "w") as f:
            while not self.stop.wait(1.0):
                load = open("/proc/loadavg").read().split()[0]
                mem = next((int(l.split()[1]) for l in open("/proc/meminfo") if l.startswith("MemAvailable:")), 0)
                f.write(f"{time.time():.1f} {load} {mem / 1048576:.1f}\n")
                f.flush()


def replica_log(replica):
    """The replica's whole module log, its files in name order (the server's data directory),
    each JSON record as the CLI prints it: `<UTC stamp>Z <LEVEL>: <message>`."""
    from datetime import datetime, timezone
    d = f"/home/spacetime/.local/share/spacetime/data/replicas/{replica}/module_logs"
    r = subprocess.run(["podman", "exec", lc.CONTAINER, "sh", "-c", f"cat $(ls -1 {d}/* | sort)"], capture_output=True, timeout=900)
    out = []
    for line in r.stdout.decode("utf-8", "replace").splitlines():
        try:
            j = json.loads(line)
        except ValueError:
            continue
        ts = int(j.get("ts", 0))
        at = datetime.fromtimestamp(ts // 1_000_000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        out.append(f"{at}.{ts % 1_000_000:06d}Z {str(j.get('level', '')).upper()}: {j.get('message', '')}")
    return "\n".join(out) + "\n"


class KeepAlive(threading.Thread):
    """The agreed keep-alive fixture (battle-views, 2026-11-19): every `every` s, each viewer
    character (a `player` row's) below its full health is set back to it with the admin's
    `admin_set_vitals` (a test fixture through the generic admin reducer, no game rule). Counts the
    calls and the health restored (from `vitals` as SQL reads it: settled at its last write)."""

    def __init__(self, db, token, every):
        super().__init__(daemon=True)
        self.db, self.token, self.every = db, token, every
        self.stop = threading.Event()
        self.calls = self.failed = 0
        self.restored = 0.0
        self.rounds = 0

    def run(self):
        while not self.stop.wait(self.every):
            try:
                chars = {r["character"] for r in lc.sql(self.db, "SELECT character FROM player", self.token)}
                hurt = [r for r in lc.sql(self.db, "SELECT id, hp, max_hp FROM vitals", self.token) if r["id"] in chars and r["hp"] < r["max_hp"]]
            except RuntimeError:
                continue
            self.rounds += 1
            for r in hurt:
                try:
                    lc.call(self.db, "admin_set_vitals", [r["id"], r["max_hp"]], self.token)
                    self.calls += 1
                    self.restored += r["max_hp"] - r["hp"]
                except RuntimeError:
                    self.failed += 1

    def summary(self, seconds):
        return {"every_s": self.every, "rounds": self.rounds, "calls": self.calls, "failed": self.failed,
                "calls_per_s": round(self.calls / seconds, 2) if seconds else None, "hp_restored": round(self.restored, 1)}


def one(a, n, out):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    db = f"verify-lookcost-{a.label}-v{n}-{stamp}"
    res = {"viewers": n, "fighters": a.fighters, "db": db}
    load = None
    try:
        lc.stdb("publish", "-s", "local", "-b", str(Path("/wasm") / a.wasm), db, "--delete-data", "-y")
        res["replica"] = lc.newest_replica()
        # Staged genesis: the world is made by scheduled steps after the publish (genesis_wait.py).
        import genesis_wait
        genesis_wait.wait_ready(lc.URL, db, lc.admin_token())
        token = lc.admin_token()
        ident = json.loads(lc.http(f"/v1/database/{db}")[1])["database_identity"]["__identity__"].removeprefix("0x")
        time.sleep(3)
        for law in a.law:
            name, value = law.split("=", 1)
            lc.call(db, "set_world_law", [name, value], token)
        if not a.battle_after_placing:
            lc.call(db, "spawn_battle", [a.fighters], token)
        land = lc.sql(db, "SELECT * FROM land", token)[0]
        site = tuple(float(x) for x in a.site.split(",")) if a.site else (land["arrive_x"], land["arrive_y"] - 20.0)
        res["site"], res["arrival"] = list(site), [land["arrive_x"], land["arrive_y"]]
        if a.paused_placement and n:
            # The Spark's procedure: paused while the viewers join and are placed, unpaused at `ready`.
            lc.call(db, "set_paused", [True], token)
        if n:
            players = [{"token": lc.new_identity(), "name": f"Watch{i}", "role": "walk"} for i in range(n)]
            load = lc.Proc([a.load, "players"], out / f"players-v{n}.stderr")
            load.send(json.dumps({"uri": lc.URL, "db": db, "events": str(out / f"events-v{n}.jsonl"), "battle": list(site),
                                  "behaviour": {"walk_period_ms": 1500, "rejoin_s": 3}, "players": players, "client": "gate",
                                  "tiers": a.tiers, "cues": a.cues, "motion_tables": a.motion_tables, "character_tables": a.character_tables, "fresh_every": a.fresh_every}))
            joined = load.expect("joined", 900)
            lo, hi = (float(x) for x in a.ring.split(",")) if a.ring else (0.0, 6.0)
            for i, p in enumerate(sorted(joined["players"], key=lambda p: p["p"])):
                # Within 6 m of the centre (the default), or spread over the ring `--ring LO,HI` m.
                ang, rr = i * 2.399963, (lo * lo + (hi * hi - lo * lo) * ((i + 0.5) / n)) ** 0.5
                try:
                    lc.call(db, "place_at", [p["id"], site[0] + rr * math.cos(ang), site[1] + rr * math.sin(ang)], token)
                except RuntimeError as e:
                    if "no such body" in str(e):
                        # Killed before it was placed: it joins again (gate-load); counted in its deaths.
                        res["unplaced"] = res.get("unplaced", 0) + 1
                        continue
                    lc.call(db, "place_at", [p["id"], site[0], site[1] + 8.0], token)
            if a.battle_after_placing:
                # The viewers stand on their ring before the fighters appear (none is killed at the
                # arrival point, 20 m from the battle, while it waits to be placed).
                lc.call(db, "spawn_battle", [a.fighters], token)
            load.send("placed")
            ready = load.expect("ready", 900)
            res["held_at_ready"] = ready.get("held")
            if a.paused_placement:
                lc.call(db, "set_paused", [False], token)
            load.send("go")
        keep = None
        if a.keep_alive and n:
            keep = KeepAlive(db, token, a.keep_alive)
            keep.start()
        time.sleep(a.warmup)
        d = out / f"v{n}"
        loadlog = None
        if a.detail or a.flip_off:
            d.mkdir(parents=True, exist_ok=True)
            pid = tc.server_pid()
            if not a.no_profile:
                lc.call(db, "set_profile", [True], token)
            loadlog = LoadLog(d / "load.log")
            loadlog.start()
            m0, th0, p0 = tc.scrape(ident), tc.thread_cpu(pid), tc.proc_cpu(pid)
        c0, t0 = tick_count(ident), time.time()
        k0 = (keep.calls, keep.restored) if keep else None
        if load:
            load.send("fresh on")
        time.sleep(a.seconds)
        c1, t1 = tick_count(ident), time.time()
        if keep:
            res["keep_alive_window"] = {"calls": keep.calls - k0[0], "hp_restored": round(keep.restored - k0[1], 1),
                                        "calls_per_s": round((keep.calls - k0[0]) / (t1 - t0), 2)}
        if load:
            load.send("fresh off")
        if loadlog:
            loadlog.stop.set()
        if a.detail or a.flip_off:
            m1, th1, p1 = tc.scrape(ident), tc.thread_cpu(pid), tc.proc_cpu(pid)
            dur = t1 - t0
            diff = {k: m1.get(k, 0.0) - m0.get(k, 0.0) for k in sorted(set(m0) | set(m1))}
            (d / "metrics.json").write_text(json.dumps({"seconds": dur, "before": m0, "after": m1, "diff": {k: v for k, v in diff.items() if v}}, indent=1) + "\n")
            import os
            hz = os.sysconf("SC_CLK_TCK")
            by = {}
            for tid, (name, cpu1) in th1.items():
                cpu0 = th0.get(tid, (name, 0))[1]
                if cpu1 - cpu0:
                    by.setdefault(name, []).append(round((cpu1 - cpu0) / hz / dur * 1000, 1))
            (d / "threads.json").write_text(json.dumps({"seconds": dur, "process_cpu_ms_per_s": round((p1 - p0) / hz / dur * 1000, 1),
                                                        "threads_cpu_ms_per_s": {k: sorted(v, reverse=True) for k, v in sorted(by.items())}}, indent=1) + "\n")
        if a.flip_off:
            # Every viewer's motion copies all public or all private (battle-views): who holds what.
            def by_viewer(table):
                got = {}
                for r in lc.sql(db, f"SELECT viewer FROM {table}", token):
                    v = r["viewer"]
                    while isinstance(v, (list, dict)):
                        v = v[0] if isinstance(v, list) else next(iter(v.values()))
                    got[v] = got.get(v, 0) + 1
                return got
            pub, far, near = by_viewer("seen_body_copy"), by_viewer("motion_seen"), by_viewer("motion_near")
            players = set(pub) | set(far) | set(near)
            res["before_flip"] = {"viewers_public": sum(1 for v in players if pub.get(v)), "viewers_private": sum(1 for v in players if far.get(v) or near.get(v)),
                                  "viewers_split": sum(1 for v in players if pub.get(v) and (far.get(v) or near.get(v))),
                                  "public_rows": sum(pub.values()), "private_rows": sum(far.values()) + sum(near.values()),
                                  "alive_players": lc.sql(db, "SELECT COUNT(*) AS n FROM player", token)[0]["n"]}
            # Control: a law change nothing in this scene reads (`takeover_s` 30 → 31; no player is
            # without its connection), so the same reinstall as the switch's but no switch; then the switch.
            time.sleep(2)
            tcz = time.time()
            lc.call(db, "set_world_law", ["takeover_s", "31.0"], token)
            time.sleep(4)
            tf = time.time()
            lc.call(db, "set_world_law", ["motion_tables_on", "false"], token)
            time.sleep(4)
            res["public_rows_after_flip"] = lc.sql(db, "SELECT COUNT(*) AS n FROM seen_body_copy", token)[0]["n"]
        if (a.detail or a.flip_off) and not a.no_profile:
            lc.call(db, "set_profile", [False], token)
            span = (t1 - t0) + a.warmup + (14 if a.flip_off else 0)
            if a.full_log:
                # A busy module's log lands late: read again until the window's tick spans are
                # all there (the server's tick counter over the window), for up to 10 minutes.
                want, waited = (c1 - c0) if c0 is not None and c1 is not None else 0, 0
                while True:
                    time.sleep(10)
                    waited += 10
                    log = replica_log(res["replica"])
                    got = len(tc.ticks(log, t0, t1).get("rows", []))
                    if got >= 0.995 * want or waited >= 600:
                        res["log_ticks"] = {"spans": got, "counter": want, "waited_s": waited}
                        break
            else:
                log = lc.stdb("logs", "-s", "local", db, "-n", str(int(span * 60 * 40 + 50_000)), timeout=900)
            (d / "module.log").write_text(log)
            (d / "ticks.json").write_text(json.dumps(tc.ticks(log, t0, t1), indent=1) + "\n")
            sp = lc.spans(log, t0, t1)
            res["spans_ms_per_s"] = {k: round(sum(v) / (t1 - t0), 2) for k, v in sorted(sp.items(), key=lambda kv: -sum(kv[1]))[:20]}
        if a.flip_off:
            moved = [l for l in log.splitlines() if "motion tables off:" in l]
            ft = tc.ticks(log, tf - 2, tf + 4)
            fs = lc.spans(log, tf - 0.5, tf + 4)
            rows = []
            rx = __import__("re").compile(r'^(\S+Z)\s.*Timing span "tick": ([\d.]+)(µs|ms|s)\b')
            for line in log.splitlines():
                mm = rx.match(line)
                if mm:
                    rows.append((line[:27], float(mm.group(2)) * {"µs": 1e-3, "ms": 1.0, "s": 1e3}[mm.group(3)]))
            (d / "flip-off.json").write_text(json.dumps({"flip_at": tf, "moved_lines": moved, "public_rows_after": res["public_rows_after_flip"],
                "motion_private_ms": fs.get("tick.motion_private"), "tick_ms_max_after": max(fs.get("tick", [0])), "ticks_around": ft}, indent=1) + "\n")
            # The kill switch's own tick: the first `tick` span logged after its "motion tables off" line
            # (the law change's reinstall freeze before it is the law reducer's, not the switch's).
            loglines = log.splitlines()
            at = next((i for i, l in enumerate(loglines) if "motion tables off:" in l), None)
            own = next((float(mm.group(2)) * {"µs": 1e-3, "ms": 1.0, "s": 1e3}[mm.group(3)] for l in loglines[at:] if (mm := rx.match(l))), None) if at is not None else None
            ts = None
            if at is not None:
                from datetime import datetime, timezone
                st = loglines[at].split("Z", 1)[0]
                ts = datetime.strptime(st, "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=timezone.utc).timestamp()
            after = tc.ticks(log, ts - 0.001, ts + 3) if ts else {}
            def after_freeze(t_a, t_b):
                """The law change's freeze in [t_a, t_b) (the widest gap between tick starts) and the
                tick after it: (gap ms, that tick's ms, its slots-late ticks in the next 3 s)."""
                rr = []
                for l in loglines:
                    mm = rx.match(l)
                    if not mm:
                        continue
                    from datetime import datetime, timezone
                    end = datetime.strptime(l.split("Z", 1)[0], "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=timezone.utc).timestamp()
                    dur = float(mm.group(2)) * {"µs": 1e-3, "ms": 1.0, "s": 1e3}[mm.group(3)]
                    if t_a <= end < t_b:
                        rr.append((end - dur / 1e3, dur))
                if len(rr) < 2:
                    return None
                i = max(range(1, len(rr)), key=lambda k: rr[k][0] - rr[k - 1][0])
                nxt = [g for g in rr[i:] if g[0] < rr[i][0] + 3]
                late = sum(1 for a2, b2 in zip(nxt, nxt[1:]) if b2[0] - a2[0] > 2 * 0.016667)
                return {"freeze_ms": round((rr[i][0] - rr[i - 1][0]) * 1e3, 1), "tick_after_ms": round(rr[i][1], 2), "late_gaps_next_3s": late}
            res["control_law_change"] = after_freeze(tcz - 0.5, tf - 0.5)
            res["switch_off"] = after_freeze(tf - 0.5, tf + 4)
            res["flip_off"] = {"moved": moved[-1].split("motion tables off: ")[1] if moved else None, "motion_private_ms": fs.get("tick.motion_private"), "switch_tick_ms": own,
                               "gap_slots_3s_from_switch": after.get("gap_slots"),
                               "tick_ms_max_after": max(fs.get("tick", [0])), "gap_slots_around": ft.get("gap_slots")}
        res["ticks_per_s"] = round((c1 - c0) / (t1 - t0), 2) if c0 is not None and c1 is not None else None
        res["alive_characters"] = lc.sql(db, "SELECT COUNT(*) AS n FROM character WHERE alive = true", token)[0]["n"]
        res["window"] = {"t0": t0, "t1": t1}
        # Liveness: the viewers' deaths in the window (gate-load's `death` events) and at the end.
        if n:
            deaths = [e for e in (json.loads(l) for l in open(out / f"events-v{n}.jsonl")) if e.get("k") == "death"]
            res["viewer_deaths"] = {"window": sum(1 for e in deaths if t0 * 1e6 <= e.get("ts", 0) < t1 * 1e6), "run": len(deaths)}
        if a.detail and a.no_profile:
            (d / "ticks.json").write_text("{}\n")
        if a.detail or a.flip_off:
            held = res.get("held_at_ready")
            chars = [h.get("characters", 0) for h in held] if isinstance(held, list) else []
            res["held_at_ready_mean"] = {"seen_characters_mean": round(sum(chars) / len(chars), 1) if chars else None}
            (d / "result.json").write_text(json.dumps({**res, "held_at_ready": res["held_at_ready_mean"]}, indent=1) + "\n")
        if keep:
            keep.stop.set()
            keep.join(timeout=30)
            res["keep_alive_run"] = keep.summary(time.time() - t0 + a.warmup)
        if load:
            load.send("stop")
            try:
                done = load.expect("done", 300)
                # Motion freshness over the window, pooled over the sampled viewers (gate-load `fresh`).
                fresh = {"near": {}, "all": {}, "players": 0}
                for pl in done.get("players", []):
                    f = pl.get("fresh")
                    if f:
                        fresh["players"] += 1
                        for group in ("near", "all"):
                            for ms, k in f[group].items():
                                fresh[group][ms] = fresh[group].get(ms, 0) + k

                def pct(h, q):
                    items = sorted((int(k), v) for k, v in h.items())
                    idx = sum(v for _, v in items) * q // 100
                    for k, v in items:
                        if idx < v:
                            return k
                        idx -= v
                    return None
                fresh["p50_p90_p95"] = {g: [pct(fresh[g], q) for q in (50, 90, 95)] for g in ("near", "all")}
                res["fresh"] = fresh
            except RuntimeError:
                pass
    finally:
        if load and load.p.poll() is None:
            load.p.terminate()
        lc.delete_world(db)
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label", required=True)
    ap.add_argument("--wasm", required=True)
    ap.add_argument("--load", required=True)
    ap.add_argument("--viewers", default="0,1,4,16")
    ap.add_argument("--fighters", type=int, default=200)
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--warmup", type=int, default=20)
    ap.add_argument("--tiers", action="store_true")
    ap.add_argument("--cues", action="store_true")
    ap.add_argument("--motion-tables", action="store_true", help="the viewers subscribe seen_body_copy in place of the motion views (battle-views)")
    ap.add_argument("--character-tables", action="store_true", help="the viewers subscribe seen_character_copy in place of seen_characters (battle-views)")
    ap.add_argument("--law", action="append", default=[])
    ap.add_argument("--fresh-every", type=int, default=0, help="sample every Nth viewer's motion freshness (gate-load `fresh`)")
    ap.add_argument("--keep-alive", type=float, default=0, metavar="SECS", help="every SECS s, set each hurt viewer back to full health (admin_set_vitals; the agreed keep-alive fixture)")
    ap.add_argument("--paused-placement", action="store_true", help="pause the world while the viewers join and are placed; unpause at ready (the Spark's procedure)")
    ap.add_argument("--site", default=None, metavar="X,Y", help="the viewers' centre (default: the arrival less 20 m, the battle's centre)")
    ap.add_argument("--battle-after-placing", action="store_true", help="spawn the battle after the viewers are placed")
    ap.add_argument("--ring", default=None, metavar="LO,HI", help="place the viewers over the ring LO-HI m from the battle's centre (outside the fighters' reach) instead of within 6 m")
    ap.add_argument("--detail", action="store_true", help="profile each window as tick_cost.py does (<out>/v<count>/)")
    ap.add_argument("--no-profile", action="store_true", help="with --detail: server metrics and thread CPU only, profiling left off (no spans)")
    ap.add_argument("--full-log", action="store_true", help="with --detail: read the replica's whole module log from the server's data directory")
    ap.add_argument("--flip-off", action="store_true", help="after the window, turn motion_tables_on off and time the kill switch's tick")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for n in (int(x) for x in a.viewers.split(",")):
        rows.append(one(a, n, out))
        print(json.dumps(rows[-1]), flush=True)
    (out / "battle-viewers.json").write_text(json.dumps({"label": a.label, "wasm": a.wasm, "laws": a.law, "rows": rows}, indent=1) + "\n")


if __name__ == "__main__":
    main()
