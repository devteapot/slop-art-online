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

`--keep-fighters SECS` (battle-laws): a sustained battle; every SECS s the fighters alive (`Fighter…`)
are counted and the dead replaced one for one with `spawn_battle` (`result.json` `keeper_window`: the
census at the window's start and end, its mean and minimum, the refills).
"""
import argparse
import json
import math
import os
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
    r = subprocess.run(["docker", "exec", lc.CONTAINER, "sh", "-c", f"cat $(ls -1 {d}/* | sort)"], capture_output=True, timeout=900)
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


def conn_lines(path, want, limit=60):
    """gate-load's `conn` lines, waiting until all `want` are on disk (its event log is buffered)."""
    t = time.time()
    while True:
        got = [json.loads(l) for l in open(path) if '"k": "conn"' in l or '"k":"conn"' in l]
        if len(got) >= want or time.time() - t > limit:
            return got
        time.sleep(0.5)


def hexid(v):
    """An identity as SQL's JSON gives it, as its 64 hex digits (gate-load's `conn` lines)."""
    import re
    m = re.search(r"[0-9a-fA-F]{64}", json.dumps(v))
    return m.group(0).lower() if m else None


def battle_spots(center, n, radius):
    """n places within `radius` m of the centre, evenly (gate.py's battle placement)."""
    out = []
    for i in range(n):
        ang, rr = i * 2.399963, radius * math.sqrt((i + 0.5) / max(n, 1))
        out.append((center[0] + rr * math.cos(ang), center[1] + rr * math.sin(ang)))
    return out


def walker_spots(db, token, n):
    """GATE_216's walkers: at lot doors, round the settlements in turn (gate.py `walker_spots`)."""
    if not n:
        return []
    by = {}
    for l in sorted(lc.sql(db, "SELECT * FROM lot", token), key=lambda l: l["id"]):
        by.setdefault(l["settlement"], []).append(l)
    order = sorted(by)
    out, k = [], 0
    while len(out) < n:
        s = by[order[k % len(order)]]
        lot = s[(k // len(order)) * 7 % len(s)]
        out.append((lot["door_x"], lot["door_y"]))
        k += 1
    return out


def steps_from(path, t0, t1):
    """The steps in the window from the tick watcher's unconfirmed connection (`u,tick,last_ms,arrival_us`):
    the interval between consecutive steps' own times (the clock's `last_ms`), and the grid steps skipped."""
    ticks = {}
    for line in open(path):
        f = line.strip().split(",")
        if len(f) != 4 or f[0] != "u":
            continue
        tick, last, arr = int(f[1]), int(f[2]), int(f[3])
        if t0 * 1e6 <= arr < t1 * 1e6:
            ticks.setdefault(tick, last)
    ks = sorted(ticks)
    iv = sorted(ticks[b] - ticks[a] for a, b in zip(ks, ks[1:]) if b == a + 1 and ticks[b] >= ticks[a])
    if not iv:
        return {"steps": len(ks)}
    q = lambda p: iv[min(len(iv) - 1, int(p * len(iv)))]
    span = ticks[ks[-1]] - ticks[ks[0]]
    return {"steps": len(ks), "span_ms": span, "steps_per_s": round((len(ks) - 1) / span * 1000, 2) if span else None,
            "interval_ms": {"p50": q(0.5), "p95": q(0.95), "p99": q(0.99), "max": iv[-1]},
            "over_25ms_pct": round(100 * sum(1 for x in iv if x > 25) / len(iv), 2), "over_50ms": sum(1 for x in iv if x > 50),
            "grid_skipped": max(0, round(span / 16.667) - (len(ks) - 1))}


def humans_from(path, h, t0, t1):
    """The human fighters' play in the window (gate-load's events): inputs a second by kind, deaths
    (each a fallen fighter that rejoins), and how their released moves came out."""
    ins, deaths, joins, outs, refused = {}, 0, 0, {}, {}
    seen_use = {}
    for line in open(path):
        e = json.loads(line)
        if e.get("p", h) >= h or not (t0 * 1e6 <= e.get("ts", 0) < t1 * 1e6):
            continue
        k = e.get("k")
        if k == "in":
            key = e["r"] if e["r"] != "skill" else f"skill:{e['skill']}"
            ins[key] = ins.get(key, 0) + 1
        elif k == "death":
            deaths += 1
        elif k == "alive":
            joins += 1
        elif k == "use" and e.get("out"):
            seen_use[(e["p"], e["use"])] = e
    for e in seen_use.values():
        word = e["out"].split(":")[0].split(",")[0].split("(")[0].strip()[:40]
        if e.get("acc"):
            outs.setdefault(e["skill"], {}).setdefault(word, 0)
            outs[e["skill"]][word] += 1
        else:
            refused.setdefault(e["skill"], {}).setdefault(word, 0)
            refused[e["skill"]][word] += 1
    dt = t1 - t0
    return {"inputs_per_s": {k: round(v / dt, 2) for k, v in sorted(ins.items())}, "inputs_total_per_s": round(sum(ins.values()) / dt, 1),
            "deaths": deaths, "deaths_per_s": round(deaths / dt, 3), "rejoined": joins, "outcomes": outs, "refused": refused}


class KeepAlive(threading.Thread):
    """The agreed keep-alive fixture (battle-views, 2026-11-19): every `every` s, each viewer
    character (a `player` row's) below its full health is set back to it with the admin's
    `admin_set_vitals` (a test fixture through the generic admin reducer, no game rule). Counts the
    calls and the health restored (from `vitals` as SQL reads it: settled at its last write)."""

    def __init__(self, db, token, every, only=None):
        super().__init__(daemon=True)
        self.db, self.token, self.every = db, token, every
        # contract-cases: only these players (identities' hex), the spectators; None: every player.
        self.only = only
        self.stop = threading.Event()
        self.calls = self.failed = 0
        self.restored = 0.0
        self.rounds = 0

    def run(self):
        while not self.stop.wait(self.every):
            try:
                chars = {r["character"] for r in lc.sql(self.db, "SELECT identity, character FROM player", self.token) if self.only is None or hexid(r["identity"]) in self.only}
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


class Keeper(threading.Thread):
    """The sustained battle (`--keep-fighters`, battle-laws, docs/COMBAT_PHASE.md): every `every` s,
    the fighters alive (characters named `Fighter…`, as `spawn_battle` names them) are counted and
    the dead replaced one for one by `spawn_battle` (the same profile: spear, fight graph, placed
    within the site's 7 m). A respawn the game does not have, as battle_diag.py's refills; it keeps
    deaths and their witnessed events in the fight. Records the census at each round."""

    def __init__(self, db, token, target, every):
        super().__init__(daemon=True)
        self.db, self.token, self.target, self.every = db, token, target, every
        self.stop = threading.Event()
        self.refills = self.failed = 0
        self.census = []

    def run(self):
        while not self.stop.wait(self.every):
            try:
                alive = sum(1 for r in lc.sql(self.db, "SELECT name FROM character WHERE alive = true", self.token) if str(r["name"]).startswith("Fighter"))
            except RuntimeError:
                continue
            self.census.append((round(time.time(), 2), alive))
            short = self.target - alive
            if short > 0:
                try:
                    lc.call(self.db, "spawn_battle", [short], self.token)
                    self.refills += short
                except RuntimeError:
                    self.failed += 1

    def window(self, t0, t1):
        inside = [n for t, n in self.census if t0 <= t <= t1]
        return {"every_s": self.every, "target": self.target, "alive_start": inside[0] if inside else None, "alive_end": inside[-1] if inside else None,
                "alive_min": min(inside, default=None), "alive_mean": round(sum(inside) / len(inside), 1) if inside else None, "rounds": len(inside)}


# ---- copy-privacy (docs/BATTLE_VIEWERS.md, "Addendum 3") ------------------------------------

_VC = Path(__file__).resolve().parents[2] / ".agents/skills/verify-client/scripts"


def _vc():
    """The verify-client probe helpers (cues.py, motion_tables.py), loaded on first use."""
    if str(_VC) not in sys.path:
        sys.path.insert(0, str(_VC))
    import cues
    import motion_tables
    return cues, motion_tables


COPY = ("seen_body_copy", "seen_character_copy")


def probe_stream(db, token, queries, seconds, path, all_tables=False):
    """The verify-client probe in stream mode from the connection on (initial rows included);
    with `all_tables`, the SDK's own `subscribe_to_all_tables` in place of `queries`."""
    cues, _ = _vc()
    req = {"uri": lc.URL, "db": db, "token": token, "queries": queries, "seconds": seconds, "stream": True, "from_start": True, "all_tables": all_tables}

    def go():
        with open(path, "w") as f:
            p = subprocess.run([str(cues.BINARY)], input=json.dumps(req), text=True, stdout=f, stderr=subprocess.DEVNULL, timeout=seconds + 120)
            f.write(json.dumps({"event": "exit", "code": p.returncode}) + "\n")
    t = threading.Thread(target=go, daemon=True)
    t.start()
    return t


def rejected(events):
    """The subscription's refusal (the probe's record with status rejected or error), or None."""
    for e in events:
        if e.get("status") in ("rejected", "error"):
            return e.get("error") or e.get("status")
    return None


class Privacy:
    """The side probes of `--privacy`, during the measured window: (a) an anonymous connection on
    both copy tables; (b) a spectator player (its own identity, joined, not a viewer) subscribing
    every public table by name, `SELECT * FROM *`, and the SDK's `subscribe_to_all_tables`; (c) one
    viewer asking for another's rows by identity, by subscription and by SQL."""

    def __init__(self, db, token, out, n, players, seconds, fighter_tables=False, combat_feed=False):
        cues, _ = _vc()
        self.db, self.out, self.n, self.players = db, out, n, players
        # With `--fighter-tables` the public fighter copies (views step 3), with `--combat-feed` the
        # combat feed's event rows (views step 2), are checked with the copy tables.
        self.tables = COPY + (("seen_fighter_copy",) if fighter_tables else ()) + (("combat_feed",) if combat_feed else ())
        ids = {}
        for l in open(out / f"events-v{n}.jsonl"):
            e = json.loads(l)
            if e.get("k") == "conn":
                ids[e["p"]] = e["identity"].lower().removeprefix("0x")
        self.ident = ids
        self.spect = lc.new_identity()
        lc.call(db, "join", ["Spectator"], self.spect)
        row = [r for r in lc.sql(db, "SELECT controller FROM character WHERE name = 'Spectator'", token)]
        self.spect_ident = cues.norm(row[0]["controller"]) if row else None
        src = "\n".join(p.read_text() for p in (Path(__file__).resolve().parents[1] / "authority/src").glob("*.rs"))
        public = sorted(set(__import__("re").findall(r"#\[spacetimedb::table\(accessor = (\w+), public", src)))
        self.k, self.j = 0, 1
        tk = players[self.k]["token"]
        peek = [f"SELECT * FROM {t} WHERE viewer = 0x{ids[self.j]}" for t in self.tables]
        self.paths = {w: out / f"privacy-v{n}-{w}.jsonl" for w in ("anon", "names", "star", "helper", "peek")}
        self.threads = [
            probe_stream(db, None, [f"SELECT * FROM {t}" for t in self.tables], seconds, self.paths["anon"]),
            probe_stream(db, self.spect, [f"SELECT * FROM {t}" for t in public], seconds, self.paths["names"]),
            probe_stream(db, self.spect, ["SELECT * FROM *"], seconds, self.paths["star"]),
            probe_stream(db, self.spect, [], seconds, self.paths["helper"], all_tables=True),
            probe_stream(db, tk, peek, seconds, self.paths["peek"]),
        ]
        self.tk = tk

    def window_checks(self):
        cues, mt = _vc()
        # While the window's streams still run: viewers' own SQL (until one that sees bodies now, so
        # the check is not vacuous; every viewer read is checked) and their SQL for another's rows.
        self.sql_read = []
        for i, p in enumerate(self.players):
            other = self.ident[(i + 1) % len(self.players)]
            own = {t: mt.player_sql(self.db, p["token"], f"SELECT * FROM {t}") for t in self.tables}
            peek = {t: mt.player_sql(self.db, p["token"], f"SELECT * FROM {t} WHERE viewer = 0x{other}") for t in self.tables}
            self.sql_read.append((i, own, peek))
            if own["seen_body_copy"]:
                break
        for t in self.threads:
            t.join()
        ev = {w: cues.lines(p) for w, p in self.paths.items()}
        rows = lambda evs: [r for t in self.tables for r in mt.copies(evs, t)]
        foreign = lambda evs, own: [r for r in rows(evs) if cues.norm(r["viewer"]) != own]
        helper_refusal = rejected(ev["helper"])
        res = {
            "anonymous: subscription accepted, no copy row": cues.accepted(ev["anon"]) and not rows(ev["anon"]),
            "spectator: every public table by name, accepted, no one else's copy row": cues.accepted(ev["names"]) and not foreign(ev["names"], self.spect_ident),
            "spectator: SELECT * FROM *, accepted, no one else's copy row": cues.accepted(ev["star"]) and not foreign(ev["star"], self.spect_ident),
            # The SDK helper names every table of the bindings, private ones too: a player's call is
            # refused as a whole (nothing delivered), or, if accepted, delivers no one else's row.
            "spectator: the SDK's subscribe_to_all_tables is refused (it names a private table), or delivers no one else's copy row": (helper_refusal is not None and "marked private" in helper_refusal and not rows(ev["helper"])) or (cues.accepted(ev["helper"]) and not foreign(ev["helper"], self.spect_ident)),
            "a viewer subscribing another viewer's rows by identity, accepted, receives none": cues.accepted(ev["peek"]) and not rows(ev["peek"]),
            "viewers' SQL reads only their own rows (one sees bodies now), none of another's by identity": bool(self.sql_read[-1][1]["seen_body_copy"])
            and all(cues.norm(r["viewer"]) == self.ident[i] for i, own, _ in self.sql_read for t in self.tables for r in own[t]) and not any(v for _, _, peek in self.sql_read for v in peek.values()),
            "every side probe ran to its end": all(e and e[-1].get("code") == 0 for e in ev.values()),
        }
        info = {"spectator": self.spect_ident, "helper": {"refused": helper_refusal, "rows": len(rows(ev["helper"]))},
                "names_rows": len(rows(ev["names"])), "star_rows": len(rows(ev["star"])),
                "sql_reads": [{"viewer": i, **{t: len(v) for t, v in own.items()}} for i, own, _ in self.sql_read]}
        return res, info

    def snapshot(self, sample, tag="window"):
        """Paused: each sampled viewer's copy tables against its views, through its own connection."""
        cues, mt = _vc()
        qs = [f"SELECT * FROM {t}" for t in (*self.tables, "seen_bodies", "seen_bodies_near", "seen_bodies_far", "seen_characters",
                                             *(("seen_fighters", "seen_fighters_near", "seen_fighters_far") if "seen_fighter_copy" in self.tables else ()))]
        paths = {i: self.out / f"privacy-v{self.n}-snap-{tag}-p{i}.jsonl" for i in sample}
        ts = [probe_stream(self.db, self.players[i]["token"], qs, 4, paths[i]) for i in sample]
        for t in ts:
            t.join()
        per = {}
        for i in sample:
            ev = cues.lines(paths[i])
            own = self.ident[i]
            table = mt.final(ev, "seen_body_copy")
            mine = {b: r for (v, b), r in table.items() if v == own}
            view = mt.final(ev, "seen_bodies")
            near, far = mt.final(ev, "seen_bodies_near"), mt.final(ev, "seen_bodies_far")
            mirror = {r["row"]["id"]: r["row"] for r in mt.final(ev, "seen_character_copy").values()}
            chars = mt.final(ev, "seen_characters")
            per[i] = {"accepted": cues.accepted(ev), "copies": len(table), "foreign": len(table) - len(mine),
                      "bodies_equal": {k: mt.moving_of(r) for k, r in mine.items()} == view,
                      "near_split_equal": {k for k, r in mine.items() if r["near"]} == set(near) and {k for k, r in mine.items() if not r["near"]} == set(far),
                      "mirror_equal": mirror == chars, "mirror_foreign": sum(1 for r in mt.final(ev, "seen_character_copy").values() if cues.norm(r["viewer"]) != own),
                      "bodies": len(view), "characters": len(chars)}
            if "seen_fighter_copy" in self.tables:
                ftable = mt.final(ev, "seen_fighter_copy")
                fmine = {r["body"]: r for r in ftable.values() if cues.norm(r["viewer"]) == own}
                fview = mt.final(ev, "seen_fighters")
                fnear, ffar = mt.final(ev, "seen_fighters_near"), mt.final(ev, "seen_fighters_far")
                per[i].update({"fighters_foreign": len(ftable) - len(fmine), "fighters": len(fview),
                               "fighters_equal": {k: r["fighter"] for k, r in fmine.items()} == fview,
                               "fighters_near_split_equal": {k for k, r in fmine.items() if r["near"]} == set(fnear) and {k for k, r in fmine.items() if not r["near"]} == set(ffar)})
        return per


def privacy_sample(out, n, k=8):
    """Up to k viewers to compare paused: the ones that died and joined again first, then spread."""
    lives = {}
    for l in open(out / f"events-v{n}.jsonl"):
        e = json.loads(l)
        if e.get("k") == "alive":
            lives[e["p"]] = lives.get(e["p"], 0) + 1
    again = sorted((p for p, v in lives.items() if v > 1), key=lambda p: -lives[p])[: k // 2]
    rest = [p for p in range(0, n, max(1, n // k)) if p not in again]
    return (again + rest)[:k]


def privacy_after_window(a, db, token, priv, load, out, n):
    """After the window: the side probes' checks; paused, the sampled viewers' tables against their
    views; then the kill switch with every viewer still connected (both laws off by row: the
    tables empty to the owner and in every viewer's cache; on again: the rows return)."""
    checks, info = priv.window_checks()
    combat = "combat_feed" in priv.tables
    lc.call(db, "set_paused", [True], token)
    time.sleep(2)
    sample = privacy_sample(out, n)
    snap = priv.snapshot(sample)
    lc.call(db, "set_paused", [False], token)
    live = [v for v in snap.values() if v["bodies"]]
    checks.update({
        "paused, sampled viewers: every snapshot accepted, no foreign row in either table": all(v["accepted"] and v["foreign"] == 0 and v["mirror_foreign"] == 0 for v in snap.values()),
        "paused, sampled viewers: seen_body_copy equals seen_bodies, near flags equal the tier split": len(live) >= max(1, len(sample) // 2) and all(v["bodies_equal"] and v["near_split_equal"] for v in snap.values()),
        "paused, sampled viewers: seen_character_copy equals seen_characters": all(v["mirror_equal"] for v in snap.values()) and any(v["characters"] for v in snap.values()),
    })
    fighters = "seen_fighter_copy" in priv.tables
    fok = lambda snapv: all(v.get("fighters_foreign", 0) == 0 and v.get("fighters_equal", True) and v.get("fighters_near_split_equal", True) for v in snapv.values())
    if fighters:
        checks["paused, sampled viewers: seen_fighter_copy equals seen_fighters, near flags equal the fighter tier split, no foreign row"] = fok(snap) and any(v.get("fighters") for v in snap.values())
    count = lambda t: lc.sql(db, f"SELECT COUNT(*) AS n FROM {t}", token)[0]["n"]
    laws = ("motion_tables_on", "characters_table_on") + (("fighter_tables_on",) if "seen_fighter_copy" in priv.tables else ())
    before = {t: count(t) for t in priv.tables}
    for law in laws:
        lc.call(db, "set_world_law", [law, "false"], token)
    time.sleep(3)
    off = {t: count(t) for t in priv.tables}
    load.send("held")
    held_off = load.expect("held", 120)["players"]
    t_on = time.time()
    for law in laws:
        lc.call(db, "set_world_law", [law, "true"], token)
    # The rows come back at each viewer's next frame (`to_public`, `fill_mirror`): the owner's
    # counts every half second for 10 s, then, paused, the sampled viewers' tables against their views.
    series = []
    while time.time() < t_on + 10:
        time.sleep(0.5)
        series.append([round(time.time() - t_on, 1), *(count(t) for t in priv.tables)])
    on = {t: count(t) for t in priv.tables}
    load.send("held")
    held_on = load.expect("held", 120)["players"]
    alive_on = [p for p in held_on if p["alive"]]
    lc.call(db, "set_paused", [True], token)
    time.sleep(2)
    snap_on = priv.snapshot(sample, "on")
    lc.call(db, "set_paused", [False], token)
    live_on = [v for v in snap_on.values() if v["bodies"]]
    checks.update({
        "kill switch: both laws off, both tables empty to the owner and in every viewer's cache": all(v == 0 for v in off.values()) and all(p["held"]["body"] == 0 and p["held"]["character"] == 0 for p in held_off),
        "kill switch: both laws on again, the rows return: paused, each sampled viewer's tables equal its views, no foreign row": all(v > 0 for v in on.values())
        and len(live_on) >= max(1, len(sample) // 2) and all(v["accepted"] and v["foreign"] == 0 and v["mirror_foreign"] == 0 and v["bodies_equal"] and v["near_split_equal"] and v["mirror_equal"] for v in snap_on.values()),
    })
    if fighters:
        checks["fighter table, law off: empty to the owner and in every viewer's cache; on again: paused, equal to the views"] = off["seen_fighter_copy"] == 0 \
            and all(p["held"].get("fighter", 0) == 0 for p in held_off) and fok(snap_on)
    return {"checks": checks, "info": info, "fighters": fighters, "combat_feed": combat, "sample": {str(k): v for k, v in snap.items()}, "sample_on": {str(k): v for k, v in snap_on.items()},
            "owner_rows": {"before": before, "off": off, "on": on, "on_series": series},
            "held_on_alive": len(alive_on), "held_on_with_bodies": sum(1 for p in alive_on if p["held"]["body"] > 0)}


def privacy_final(pr, done, out, n):
    """From gate-load's `done`: every copy row each viewer received, over the whole run, was its own."""
    ps = [p for p in done.get("players", []) if p.get("privacy")]
    tot = {k: sum(p["privacy"].get(k, 0) for p in ps) for k in ("body_rows", "character_rows", "fighter_rows", "combat_rows", "foreign_rows")}
    pr["viewer_rows"] = {**tot, "players": len(ps), "without_body_rows": sum(1 for p in ps if not p["privacy"]["body_rows"]),
                         "without_character_rows": sum(1 for p in ps if not p["privacy"]["character_rows"]),
                         "foreign_viewers": sorted({v for p in ps for v in p["privacy"]["foreign_viewers"]})[:8]}
    pr["checks"].update({
        "every viewer's copy rows over the run (initial, inserts, updates) name it as the viewer": len(ps) == n and tot["foreign_rows"] == 0,
        "every viewer received copy rows of both tables (the check is not vacuous)": len(ps) == n and pr["viewer_rows"]["without_body_rows"] == 0 and pr["viewer_rows"]["without_character_rows"] == 0,
    })
    if pr.get("fighters"):
        pr["checks"]["the viewers received seen_fighter_copy rows, all their own (counted with the copies above)"] = tot["fighter_rows"] > 0 and tot["foreign_rows"] == 0
    if pr.get("combat_feed"):
        pr["checks"]["the viewers received combat_feed event rows, all their own (counted with the copies above)"] = tot["combat_rows"] > 0 and tot["foreign_rows"] == 0
    (out / f"privacy-v{n}.json").write_text(json.dumps(pr, indent=1) + "\n")


CLOG = "/home/spacetime/.local/share/spacetime/data/replicas/{}/clog"


def clog_state(replica):
    """A replica's commitlog on disk: its bytes (du -sb), its segments' bytes as read (`log_bytes`,
    the cumulative log position clog_read.py --byte-range takes; raw segments only) and its segment
    files (`*.stdb.log`)."""
    r = subprocess.run(["docker", "exec", lc.CONTAINER, "sh", "-c", f"du -sb {CLOG.format(replica)}; cat {CLOG.format(replica)}/*.stdb.log | wc -c; ls {CLOG.format(replica)}"], capture_output=True, text=True)
    lines = r.stdout.split("\n")
    return {"bytes": int(lines[0].split()[0]), "log_bytes": int(lines[1].split()[0]), "segments": sum(1 for x in lines[2:] if x.endswith(".stdb.log")), "files": sum(1 for x in lines[2:] if x.strip())}


def clog_zstd(replica):
    """The commitlog's segments (`*.stdb.log`) compressed: bytes raw, at zstd -3 (the level 2.14.1
    uses for sealed segments behind a snapshot) and zstd -6 (as trial_archive.py keeps them), or
    None. Read after the world is deleted: a deleted database's files stay and no longer change."""
    cat = ["docker", "exec", lc.CONTAINER, "sh", "-c", f"cat {CLOG.format(replica)}/*.stdb.log"]
    out = {}
    for name, cmd in (("raw", ["wc", "-c"]), ("zstd3", ["sh", "-c", "zstd -3 -q -c -T0 | wc -c"]), ("zstd6", ["sh", "-c", "zstd -6 -q -c -T0 | wc -c"])):
        src = subprocess.Popen(cat, stdout=subprocess.PIPE)
        r = subprocess.run(cmd, stdin=src.stdout, capture_output=True, text=True)
        src.stdout.close()
        if src.wait() != 0 or r.returncode != 0:
            return None
        out[name] = int(r.stdout.split()[0])
    return out


def spawn(db, token, a):
    """The battle: `spawn_battle`, or with `--sides N` the fixture `spawn_battle_sides` (fighters in
    N sides that fight each other and leave bystanders be; docs/BATTLE_LAWS.md)."""
    ai = a.fighters - a.humans
    if ai <= 0:
        return
    if a.sides:
        lc.call(db, "spawn_battle_sides", [ai, a.sides], token)
    else:
        lc.call(db, "spawn_battle", [ai], token)


def one(a, n, out):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    db = f"verify-lookcost-{a.label}-v{n}-{stamp}"
    res = {"viewers": n, "fighters": a.fighters, "humans": a.humans, "walkers": a.walkers, "db": db}
    total = n + a.humans + a.walkers
    watch = None
    load = None
    priv = None
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
        # With no viewers there is no placement to wait for, so `--battle-after-placing` spawns the
        # battle here too: the 0-viewer arm is the same battle, the subtraction baseline (before
        # 2026-11-20 it had none).
        if not a.battle_after_placing or not total:
            spawn(db, token, a)
        land = lc.sql(db, "SELECT * FROM land", token)[0]
        site = tuple(float(x) for x in a.site.split(",")) if a.site else (land["arrive_x"], land["arrive_y"] - 20.0)
        res["site"], res["arrival"] = list(site), [land["arrive_x"], land["arrive_y"]]
        relay_p = checker_p = clients_p = None
        if a.relay:
            # RELAY_PROTOTYPE (relay-proto): the delivery relay and the privacy checker, each an owner
            # connection, from the world's first ticks (living/tools/relay_proto).
            rq = {"uri": lc.URL, "db": db, "token": token}
            relay_p = lc.Proc([a.relay, "relay"], out / "relay.stderr")
            relay_p.send(json.dumps({**rq, "listen": f"127.0.0.1:{a.relay_port}", "out": str(out / "relay.json"), "broken": a.relay_broken}))
            relay_p.expect("relay up", 120)
            checker_p = lc.Proc([a.relay, "checker"], out / "checker.stderr")
            checker_p.send(json.dumps({**rq, "out": str(out / "checker.log")}))
            checker_p.expect("checker up", 120)
        perc_p = None
        if a.relay and a.perc:
            # PERCEPTION_OFF_THREAD (perc-offthread): the off-thread perception stand-in (set the
            # perc_external law), an owner connection applying sets through `perc_apply`.
            perc_p = lc.Proc([a.relay, "perc"], out / "perc.stderr")
            perc_p.send(json.dumps({"uri": lc.URL, "db": db, "token": token, "out": str(out / "perc.json"), "cap": a.perc_cap, "keep_n": a.perc_keep, "swap": a.perc_swap}))
            perc_p.expect("perc up", 120)
        if a.watch:
            # BATTLE_CONTRACT_CASES (contract-cases): the tick watcher (gate-load `watch`, as GATE_216):
            # two owner connections subscribing `clock`, which every tick writes; the steps' intervals.
            watch = lc.Proc([a.load, "watch"], out / "watch.stderr")
            watch.send(json.dumps({"uri": lc.URL, "db": db, "token": token, "out": str(out / "ticks-watch.csv")}))
            watch.expect("ready", 120)
        if a.paused_placement and total:
            # The Spark's procedure: paused while the viewers join and are placed, unpaused at `ready`.
            lc.call(db, "set_paused", [True], token)
        if total:
            # BATTLE_CONTRACT_CASES (contract-cases): `--humans` human fighters first (GATE_216's battle
            # role, placed in the fighters' 7 m), then the `n` spectators, then `--walkers` at lot doors.
            players = ([{"token": lc.new_identity(), "name": f"Human{i}", "role": "battle"} for i in range(a.humans)]
                       + [{"token": lc.new_identity(), "name": f"Watch{i}", "role": "walk"} for i in range(n)]
                       + [{"token": lc.new_identity(), "name": f"Walk{i}", "role": "walk"} for i in range(a.walkers)])
            load = lc.Proc([a.load, "players"], out / f"players-v{n}.stderr")
            load.send(json.dumps({"uri": lc.URL, "db": db, "events": str(out / f"events-v{n}.jsonl"), "battle": list(site),
                                  "relay": f"ws://127.0.0.1:{a.relay_port}" if a.relay and a.humans else None,
                                  "behaviour": {"walk_period_ms": 1500, "fight_period_ms": a.fight_ms, "rejoin_s": 3, "pools": True}, "players": players, "client": "gate",
                                  "tiers": a.tiers, "cues": a.cues, "motion_tables": a.motion_tables, "character_tables": a.character_tables, "fighter_tables": a.fighter_tables,
                                  "combat_feed": a.combat_feed, "crowd": a.crowd, "lines_table": a.lines_table, "game_views": a.game_views, "fresh_every": a.fresh_every}))
            joined = load.expect("joined", 900)
            lo, hi = (float(x) for x in a.ring.split(",")) if a.ring else (0.0, 6.0)
            humans_at = battle_spots(site, a.humans, 7.0)
            walkers_at = walker_spots(db, token, a.walkers)
            for k, p in enumerate(sorted(joined["players"], key=lambda p: p["p"])):
                i = k - a.humans
                if k < a.humans:
                    x, y = humans_at[k]
                elif i >= n:
                    x, y = walkers_at[i - n]
                else:
                    # Within 6 m of the centre (the default), or spread over the ring `--ring LO,HI` m.
                    ang, rr = i * 2.399963, (lo * lo + (hi * hi - lo * lo) * ((i + 0.5) / n)) ** 0.5
                    x, y = site[0] + rr * math.cos(ang), site[1] + rr * math.sin(ang)
                try:
                    lc.call(db, "place_at", [p["id"], x, y], token)
                except RuntimeError as e:
                    if "no such body" in str(e):
                        # Killed before it was placed: it joins again (gate-load); counted in its deaths.
                        res["unplaced"] = res.get("unplaced", 0) + 1
                        continue
                    lc.call(db, "place_at", [p["id"], site[0], site[1] + 8.0], token)
            if a.battle_after_placing:
                # The viewers stand on their ring before the fighters appear (none is killed at the
                # arrival point, 20 m from the battle, while it waits to be placed).
                spawn(db, token, a)
            load.send("placed")
            ready = load.expect("ready", 900)
            res["held_at_ready"] = ready.get("held")
            if a.paused_placement:
                lc.call(db, "set_paused", [False], token)
            load.send("go")
            if a.humans:
                load.send("battle")
        keeper = None
        if a.keep_fighters and a.fighters - a.humans > 0:
            keeper = Keeper(db, token, a.fighters - a.humans, a.keep_fighters)
            keeper.start()
        npc_p = None
        if a.npc_share is not None:
            # NPC-MEASURE (npc-measure): the stand-in NPC body service (gate-load `npc`), an owner
            # connection driving the fighters with `id % 4 < share` through `npc_intents` (set the
            # npc_external_on law); with share 0 it only records the fighter rows (the AI arm).
            npc_p = lc.Proc([a.load, "npc"], out / "npc.stderr")
            npc_p.send(json.dumps({"uri": lc.URL, "db": db, "token": token, "out": str(out), "share": a.npc_share, "decide_ms": a.npc_decide_ms, "react": True}))
            npc_p.expect("ready", 120)
            npc_p.send("go")
        relay = None
        if a.relay_sub:
            # BATTLE_DELIVERY_PATHS (viewer-floor): one privileged subscriber to the battle's truth
            # tables, as a delivery relay would hold, through the container's owner login.
            relay = subprocess.Popen(["docker", "exec", "-e", "TOKIO_WORKER_THREADS=1", lc.CONTAINER, "spacetime", "subscribe", "-s", "local", "-y", db,
                                      *[f"SELECT * FROM {t}" for t in a.relay_sub.split(",")]], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if a.relay and total:
            # The viewers' identities, from gate-load's connection lines; one relay client each. A human
            # fighter reads the relay from gate-load itself (contract-cases), so it is not among them.
            ids = [e["identity"] for e in conn_lines(out / f"events-v{n}.jsonl", total) if e.get("role") != "Battle"]
            clients_p = lc.Proc([a.relay, "clients"], out / "clients.stderr")
            clients_p.send(json.dumps({"relay": f"ws://127.0.0.1:{a.relay_port}", "viewers": ids, "out": str(out / "clients.json"), "warmup": a.warmup}))
            clients_p.expect("clients up", 120)
            res["relay_viewers"] = len(ids)
            (out / "relay-ids.json").write_text(json.dumps(ids) + "\n")
        keep = None
        if a.keep_alive and n:
            # Only the spectators are kept alive: human fighters fall and rejoin (contract-cases).
            conns = conn_lines(out / f"events-v{n}.jsonl", total)
            spect = {c["identity"] for c in conns if a.humans <= c["p"] < a.humans + n}
            keep = KeepAlive(db, token, a.keep_alive, spect if (a.humans or a.walkers) else None)
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
            relay_cpu0 = tc.proc_cpu(relay_p.p.pid) if relay_p else None
            relay_t0 = time.time()
        if a.privacy and n:
            priv = Privacy(db, token, out, n, players, a.seconds, a.fighter_tables, a.combat_feed)
        clog0 = clog_state(res["replica"]) if a.clog else None
        c0, t0 = tick_count(ident), time.time()
        k0 = (keep.calls, keep.restored) if keep else None
        f0 = keeper.refills if keeper else 0
        if load:
            load.send("fresh on")
        flip = None
        if a.flip_law:
            # E2 (attention-e2): one law set live mid-window (a capacity burst); its time is kept so
            # the ticks around it can be read from ticks.json.
            name, _, value = a.flip_law.partition("=")
            time.sleep(a.flip_at)
            t_flip = time.time()
            lc.call(db, "set_world_law", [name, value], token)
            flip = {"law": name, "value": value, "at": t_flip, "acked": time.time()}
            time.sleep(max(0.0, a.seconds - a.flip_at))
        else:
            time.sleep(a.seconds)
        c1, t1 = tick_count(ident), time.time()
        if flip:
            res["flip_law"] = flip
        if relay:
            alive = relay.poll() is None
            subprocess.run(["docker", "exec", lc.CONTAINER, "pkill", "-f", "spacetime subscribe"], capture_output=True)
            try:
                relay.wait(30)
            except subprocess.TimeoutExpired:
                relay.kill()
            res["relay_sub"] = {"tables": a.relay_sub, "alive_at_window_end": alive, "stderr": (relay.stderr.read() or "")[-400:]}
        if keeper:
            keeper.stop.set()
            res["keeper_window"] = keeper.window(t0, t1)
            res["keeper_window"]["refills"] = keeper.refills - f0
            res["keeper_window"]["refills_per_s"] = round((keeper.refills - f0) / (t1 - t0), 2)
        if a.clog:
            # Commitlog growth over the window: the replica's `clog/` on disk (segments and their
            # offset indexes), not what a snapshot would let go (docs/TRIAL_DISK.md).
            clog1 = clog_state(res["replica"])
            dt = t1 - t0
            grew = clog1["bytes"] - clog0["bytes"]
            res["clog"] = {"start": clog0, "end": clog1, "seconds": round(dt, 2), "bytes": grew,
                           "bytes_per_s": round(grew / dt, 1), "bytes_per_hour": round(grew / dt * 3600),
                           "segments_added": clog1["segments"] - clog0["segments"]}
        if keep:
            res["keep_alive_window"] = {"calls": keep.calls - k0[0], "hp_restored": round(keep.restored - k0[1], 1),
                                        "calls_per_s": round((keep.calls - k0[0]) / (t1 - t0), 2)}
        if load:
            load.send("fresh off")
        if npc_p:
            npc_p.send("stop")
            res["npc"] = npc_p.expect("done", 60)
            res["npc"]["window"] = [t0, t1]
        if watch:
            watch.send("stop")
            try:
                watch.p.wait(30)
            except subprocess.TimeoutExpired:
                watch.p.kill()
            res["steps"] = steps_from(out / "ticks-watch.csv", t0, t1)
        if a.humans:
            res["humans_window"] = humans_from(out / f"events-v{n}.jsonl", a.humans, t0, t1)
        if loadlog:
            loadlog.stop.set()
        if relay_p and (a.detail or a.flip_off):
            hz = os.sysconf("SC_CLK_TCK")
            st = {l.split(":")[0]: int(l.split()[1]) for l in open(f"/proc/{relay_p.p.pid}/status") if l.startswith(("VmRSS", "VmHWM"))}
            res["relay_process"] = {"cpu_ms_per_s": round((tc.proc_cpu(relay_p.p.pid) - relay_cpu0) / hz / (time.time() - relay_t0) * 1000, 1),
                                    "rss_kb": st.get("VmRSS"), "hwm_kb": st.get("VmHWM")}
            if clients_p:
                res["relay_process"]["clients_cpu_ms_per_s"] = round((tc.proc_cpu(clients_p.p.pid)) / hz / max(time.time() - relay_t0, 1) * 1000, 1)
        if perc_p and (a.detail or a.flip_off):
            res.setdefault("relay_process", {})["perc_cpu_ms_per_s"] = round(tc.proc_cpu(perc_p.p.pid) / os.sysconf("SC_CLK_TCK") / max(time.time() - relay_t0, 1) * 1000, 1)
        for proc in (clients_p, relay_p, checker_p, perc_p):
            if proc:
                proc.send("stop")
                try:
                    proc.p.wait(60)
                except subprocess.TimeoutExpired:
                    proc.p.kill()
        if relay_p:
            for f in ("relay.json", "clients.json", "perc.json"):
                if (out / f).exists():
                    res[f.split(".")[0] + "_summary"] = json.loads((out / f).read_text())
        if a.detail or a.flip_off:
            m1, th1, p1 = tc.scrape(ident), tc.thread_cpu(pid), tc.proc_cpu(pid)
            dur = t1 - t0
            diff = {k: m1.get(k, 0.0) - m0.get(k, 0.0) for k in sorted(set(m0) | set(m1))}
            (d / "metrics.json").write_text(json.dumps({"seconds": dur, "before": m0, "after": m1, "diff": {k: v for k, v in diff.items() if v}}, indent=1) + "\n")
            hz = os.sysconf("SC_CLK_TCK")
            by = {}
            for tid, (name, cpu1) in th1.items():
                cpu0 = th0.get(tid, (name, 0))[1]
                if cpu1 - cpu0:
                    by.setdefault(name, []).append(round((cpu1 - cpu0) / hz / dur * 1000, 1))
            (d / "threads.json").write_text(json.dumps({"seconds": dur, "process_cpu_ms_per_s": round((p1 - p0) / hz / dur * 1000, 1),
                                                        "threads_cpu_ms_per_s": {k: sorted(v, reverse=True) for k, v in sorted(by.items())}}, indent=1) + "\n")
        if priv:
            res["privacy"] = privacy_after_window(a, db, token, priv, load, out, n)
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
                # E2 (attention-e2): what the viewers received, by table, over the whole run
                # (inserts, updates, deletes; gate-load counts from its subscription on).
                tables = {}
                for pl in done.get("players", []):
                    for t, n in (pl.get("events") or {}).items():
                        acc = tables.setdefault(t, [0, 0, 0])
                        for i in range(3):
                            acc[i] += n[i]
                res["viewer_rows_by_table"] = tables
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
                if priv:
                    privacy_final(res["privacy"], done, out, n)
            except RuntimeError:
                pass
    finally:
        if load and load.p.poll() is None:
            load.p.terminate()
        if a.keep_world:
            # Left paused for what follows (clog_read.py, an offline prune trial); deleted later
            # with world_delete.py.
            import world_delete
            tok = lc.admin_token()
            res["kept"] = world_delete.pause_confirmed(
                pause=lambda: lc.http(f"/v1/database/{db}/call/set_paused", [True], tok)[0],
                read=lambda: lc.http(f"/v1/database/{db}/sql", "SELECT paused FROM world", tok, raw=True))
        else:
            lc.delete_world(db)
        if a.clog and "clog" in res and not a.keep_world:
            # The whole commitlog compressed, as the server keeps sealed segments behind a snapshot
            # (zstd -3) and as an archive keeps it (zstd -6).
            z = clog_zstd(res["replica"])
            res["clog"]["zstd"] = z
            if z and z["raw"]:
                res["clog"]["zstd3_ratio"] = round(z["zstd3"] / z["raw"], 4)
                res["clog"]["zstd6_ratio"] = round(z["zstd6"] / z["raw"], 4)
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
    ap.add_argument("--keep-fighters", type=float, default=0, metavar="SECS", help="a sustained battle: every SECS s, replace dead fighters one for one with spawn_battle (battle-laws)")
    ap.add_argument("--keep-alive", type=float, default=0, metavar="SECS", help="every SECS s, set each hurt viewer back to full health (admin_set_vitals; the agreed keep-alive fixture)")
    ap.add_argument("--paused-placement", action="store_true", help="pause the world while the viewers join and are placed; unpause at ready (the Spark's procedure)")
    ap.add_argument("--site", default=None, metavar="X,Y", help="the viewers' centre (default: the arrival less 20 m, the battle's centre)")
    ap.add_argument("--battle-after-placing", action="store_true", help="spawn the battle after the viewers are placed")
    ap.add_argument("--ring", default=None, metavar="LO,HI", help="place the viewers over the ring LO-HI m from the battle's centre (outside the fighters' reach) instead of within 6 m")
    ap.add_argument("--detail", action="store_true", help="profile each window as tick_cost.py does (<out>/v<count>/)")
    ap.add_argument("--no-profile", action="store_true", help="with --detail: server metrics and thread CPU only, profiling left off (no spans)")
    ap.add_argument("--full-log", action="store_true", help="with --detail: read the replica's whole module log from the server's data directory")
    ap.add_argument("--flip-off", action="store_true", help="after the window, turn motion_tables_on off and time the kill switch's tick")
    ap.add_argument("--fighter-tables", action="store_true", help="the viewers subscribe seen_fighter_copy in place of the fighter views (views step 3; set fighter_tables_on=true)")
    ap.add_argument("--flip-law", default=None, metavar="NAME=VALUE", help="E2: set this world law live --flip-at s into the window (a capacity burst)")
    ap.add_argument("--flip-at", type=float, default=30.0)
    ap.add_argument("--relay", default="", help="RELAY_PROTOTYPE (relay-proto): the relay_proto binary; runs the relay, the privacy checker and one relay client per viewer (set the relay_on law)")
    ap.add_argument("--perc", action="store_true", help="PERCEPTION_OFF_THREAD (perc-offthread): with --relay, also run the off-thread perception stand-in (set perc_external)")
    ap.add_argument("--perc-cap", type=int, default=11, help="the stand-in's set size (heed at 16 attends about 10.6 at contract density)")
    ap.add_argument("--perc-swap", type=float, default=0.0, help="the stand-in's extra churn: the share of viewer rounds that swap one member")
    ap.add_argument("--perc-keep", type=int, default=12, help="the stand-in keeps a member while it stays within this many nearest (sets the churn)")
    ap.add_argument("--relay-broken", action="store_true", help="the relay applies a transaction's state before its set changes (the privacy probe's known answer)")
    ap.add_argument("--relay-port", type=int, default=3391)
    ap.add_argument("--relay-sub", default="", help="BATTLE_DELIVERY_PATHS: comma-separated truth tables one privileged subscriber holds over the run (a relay's feed)")
    ap.add_argument("--game-views", action="store_true", help="VIEWER_FLOOR (viewer-floor): the viewers also subscribe the game client's other views (heard_sounds, my_earshot, my_senses, my_act_outcomes, my_offers, my_known_names, my_records, speech_card, cover_law)")
    ap.add_argument("--crowd", action="store_true", help="E2 prototype (attention-e2): the viewers also subscribe seen_crowd (set attend_n and attend_crowd_on)")
    ap.add_argument("--combat-feed", action="store_true", help="the viewers subscribe combat_feed in place of my_combat (views step 2; set combat_feed_on=true)")
    ap.add_argument("--keep-world", action="store_true", help="leave the world paused at the end instead of deleting it (read back as paused)")
    ap.add_argument("--clog", action="store_true", help="record the replica's commitlog growth on disk over the window, and its compressed size after the world is deleted, zstd -3 and -6 (result clog)")
    ap.add_argument("--sides", type=int, default=0, help="the fighters in this many sides (2-4) that fight each other, not bystanders (spawn_battle_sides)")
    ap.add_argument("--privacy", action="store_true", help="copy-privacy: prove each viewer receives only its own copy rows (needs --motion-tables --character-tables and both laws on); <out>/privacy-v<count>.json, exit 1 on a failed check")
    ap.add_argument("--lines-table", action="store_true", help="gate-remeasure: the players read experience_copy in place of my_experience, as the shipped client")
    ap.add_argument("--humans", type=int, default=0, help="BATTLE_CONTRACT_CASES (contract-cases): this many of the --fighters are human clients (gate-load's battle role, GATE_216's decisions), placed in the fighters' 7 m; the AI fighters are the rest")
    ap.add_argument("--walkers", type=int, default=0, help="contract-cases: also this many walkers at lot doors round the settlements (GATE_216's walkers)")
    ap.add_argument("--fight-ms", type=int, default=250, help="contract-cases: a human fighter's decision period (GATE_216: 250 ms ±10%%)")
    ap.add_argument("--npc-share", type=int, default=None, help="NPC-MEASURE (npc-measure): run the stand-in NPC body service driving the fighters with id %% 4 < SHARE (0: record only); set npc_external_on")
    ap.add_argument("--npc-decide-ms", type=int, default=100, help="npc-measure: each driven NPC's decision period")
    ap.add_argument("--watch", action="store_true", help="contract-cases: run the tick watcher (gate-load watch) for the steps' intervals (result steps)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.privacy and (a.flip_off or not (a.motion_tables and a.character_tables) or not {"motion_tables_on=true", "characters_table_on=true"} <= set(a.law)):
        ap.error("--privacy needs --motion-tables --character-tables --law motion_tables_on=true --law characters_table_on=true, and not --flip-off")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for n in (int(x) for x in a.viewers.split(",")):
        rows.append(one(a, n, out))
        print(json.dumps(rows[-1]), flush=True)
    (out / "battle-viewers.json").write_text(json.dumps({"label": a.label, "wasm": a.wasm, "laws": a.law, "rows": rows}, indent=1) + "\n")
    if a.privacy:
        failed = [(r["viewers"], k) for r in rows if r.get("privacy") for k, v in r["privacy"]["checks"].items() if not v]
        for r in rows:
            for k, v in (r.get("privacy") or {}).get("checks", {}).items():
                print(("PASS " if v else "FAIL ") + f"v{r['viewers']}: {k}")
        final = "every viewer's copy rows over the run (initial, inserts, updates) name it as the viewer"
        whole = all(final in r["privacy"]["checks"] for r in rows if r.get("privacy"))
        if not whole:
            print("FAIL: gate-load's `done` never came, so the viewers' own counts are missing")
        sys.exit(1 if failed or not whole or not any(r.get("privacy") for r in rows) else 0)


if __name__ == "__main__":
    main()
