#!/usr/bin/env python3
"""The projection's cost with and without looks (look-1, docs/LOOK.md §4 "Measure before
acceptance"): the `tick.perception` span and the bytes of `seen_characters`, for one module build
under a crowd of real players.

    look_cost.py --label NAME --wasm FILE --load GATE_LOAD [--players 216 --groups 7 --radius 3
                 --warmup 30 --seconds 120] [--container C --url U]

What it does, in order:
1. Publishes `/wasm/FILE` (a file in the server's `/wasm` mount) fresh as `verify-lookcost-<label>-<stamp>`
   on the worker's own server (`LIVING_STDB_CONTAINER`, `LIVING_STDB_URL`). The module's `init`
   installs its compiled script and creates the world from its compiled seed.
2. Joins `--players` real players over their own WebSocket connections (`gate-load players`,
   living/tools/gate_load; the gate's client query set) and places them (admin `place_at`) in
   `--groups` clusters of `--radius` m round lot doors at least 40 m apart, so each sees about
   players/groups others. They walk small circles (the gate's walkers: a new direction every
   1.5 s), coming into and going out of one another's sight at the edges.
3. Warm-up, then profiling on (`set_profile`) for the measured window: the module's `Timing span`
   lines give ms of each span per second (`tick.perception`, `tick`, `housekeeping`); the server's
   `spacetime_num_bytes_sent_to_clients_total` for this database gives bytes sent per second.
4. At the end, as each of a sample of players (its own token), `SELECT * FROM seen_characters`:
   the rows each holds and their BSATN size (strings are a u32 length and the bytes), so the
   bytes the `look` column adds per row are exact; and as the owner, the `projected` and `look`
   row counts.
5. Deletes the database. Writes `<out>/result.json` and the module log. Python standard library.

It never touches another database: the name it publishes starts `verify-lookcost-`.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTAINER = os.environ.get("LIVING_STDB_CONTAINER", "look1-stdb")
URL = os.environ.get("LIVING_STDB_URL", "http://127.0.0.1:3337").rstrip("/")


def sh(*args, timeout=600, check=True):
    r = subprocess.run([*map(str, args)], capture_output=True, text=True, timeout=timeout)
    if check and r.returncode:
        raise RuntimeError(f"{' '.join(map(str, args))[:160]}: {r.stderr[-800:]}")
    return r.stdout


def stdb(*args, timeout=600):
    return sh("podman", "exec", "-i", CONTAINER, "spacetime", *args, timeout=timeout)


def http(path, body=None, token=None, raw=False):
    data = body.encode() if raw else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(URL + path, data=data, method="POST" if data is not None or path == "/v1/identity" else "GET")
    if data is not None and not raw:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def sql(db, q, token):
    code, body = http(f"/v1/database/{db}/sql", q, token, raw=True)
    if code != 200:
        raise RuntimeError(f"sql {q!r}: {code} {body[:300]}")
    res = json.loads(body)[0]
    names = [e["name"]["some"] if isinstance(e["name"], dict) else e["name"] for e in res["schema"]["elements"]]
    return [dict(zip(names, r)) for r in res["rows"]]


def call(db, reducer, args, token):
    code, body = http(f"/v1/database/{db}/call/{reducer}", args, token)
    if code != 200:
        raise RuntimeError(f"{reducer}{args}: {code} {body[:300]}")


def new_identity():
    """A fresh identity's token; retried, since a busy server sometimes resets the connection."""
    for attempt in range(5):
        try:
            return json.loads(http("/v1/identity", {})[1])["token"]
        except OSError:
            if attempt == 4:
                raise
            time.sleep(1)


def admin_token():
    found = re.findall(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", stdb("login", "show", "--token"))
    assert len(found) == 1, "the container CLI's token"
    return found[0]


def bytes_sent(ident):
    text = urllib.request.urlopen(f"{URL}/v1/metrics", timeout=60).read().decode()
    out = {}
    for m in re.finditer(r'^spacetime_num_bytes_sent_to_clients_total\{db="([0-9a-f]+)",txn_type="(\w+)"\} (\d+)', text, re.M):
        if m.group(1) == ident:
            out[m.group(2)] = int(m.group(3))
    return out


def bsatn(row):
    """A `SeenCharacter` row's BSATN size: u32, String ×5 (+ `look` when present), u8, bool, u8, f32 ×2."""
    n = 4 + 1 + 1 + 1 + 4 + 4
    for k in ("name", "label", "kind", "folk", "style", "look"):
        if k in row:
            n += 4 + len(row[k].encode())
    return n


def clusters(lots, groups, radius, per):
    doors, centers = [(l["door_x"], l["door_y"]) for l in sorted(lots, key=lambda l: l["id"])], []
    for d in doors:
        if all((d[0] - c[0]) ** 2 + (d[1] - c[1]) ** 2 >= 40.0 ** 2 for c in centers):
            centers.append(d)
        if len(centers) == groups:
            break
    assert len(centers) == groups, f"only {len(centers)} doors 40 m apart"
    spots = []
    for c in centers:
        for i in range(per):
            a, rr = i * 2.399963, radius * ((i + 0.5) / per) ** 0.5
            import math
            spots.append((c[0] + rr * math.cos(a), c[1] + rr * math.sin(a)))
    return centers, spots


class Proc:
    def __init__(self, cmd, err):
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=open(err, "w"), text=True, start_new_session=True)

    def send(self, line):
        self.p.stdin.write(line + "\n")
        self.p.stdin.flush()

    def expect(self, event, timeout):
        box = {}

        def read():
            for line in self.p.stdout:
                try:
                    v = json.loads(line)
                except ValueError:
                    continue
                if v.get("event") == event:
                    box["v"] = v
                    return

        t = threading.Thread(target=read, daemon=True)
        t.start()
        t.join(timeout)
        if "v" not in box:
            raise RuntimeError(f"no {event} within {timeout}s (exit {self.p.poll()})")
        return box["v"]


def spans(log, t0, t1):
    rx = re.compile(r'^(\S+Z)\s.*Timing span "([^"]+)": ([\d.]+)(µs|ms|s)\b')
    out = {}
    for line in log.splitlines():
        m = rx.match(line)
        if not m:
            continue
        stamp = m.group(1).rstrip("Z")[:26]
        at = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%f" if "." in stamp else "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
        if t0 <= at < t1:
            out.setdefault(m.group(2), []).append(float(m.group(3)) * {"µs": 1e-3, "ms": 1.0, "s": 1e3}[m.group(4)])
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label", required=True)
    ap.add_argument("--wasm", required=True, help="a file in the server's /wasm mount")
    ap.add_argument("--load", required=True, help="the gate-load binary built against the module's bindings")
    ap.add_argument("--players", type=int, default=216)
    ap.add_argument("--groups", type=int, default=7)
    ap.add_argument("--radius", type=float, default=3.0)
    ap.add_argument("--warmup", type=int, default=30)
    ap.add_argument("--seconds", type=int, default=120)
    ap.add_argument("--sample", type=int, default=24)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    db = f"verify-lookcost-{a.label}-{stamp}"
    out = Path(a.out or ROOT / ".local/look1/cost" / f"{a.label}-{stamp}")
    out.mkdir(parents=True, exist_ok=True)
    res = {"label": a.label, "db": db, "wasm": a.wasm, "players": a.players, "groups": a.groups, "radius_m": a.radius, "warmup_s": a.warmup, "window_s": a.seconds}
    load = None
    try:
        stdb("publish", "-s", "local", "-b", f"/wasm/{a.wasm}", db, "--delete-data", "-y")
        token = admin_token()
        ident = json.loads(http(f"/v1/database/{db}")[1])["database_identity"]["__identity__"].removeprefix("0x")
        time.sleep(3)
        world = sql(db, "SELECT * FROM world", token)[0]
        res["world"] = {k: world.get(k) for k in ("run", "seed", "day_ms", "look_book")}
        tokens = [new_identity() for _ in range(a.players)]
        players = [{"token": t, "name": f"Cost{i}", "role": "walk"} for i, t in enumerate(tokens)]
        load = Proc([a.load, "players"], out / "players.stderr")
        load.send(json.dumps({"uri": URL, "db": db, "events": str(out / "events.jsonl"), "battle": [0.0, 0.0], "behaviour": {"walk_period_ms": 1500, "rejoin_s": 3}, "players": players, "client": "gate"}))
        joined = load.expect("joined", 900)
        ids = [p["id"] for p in sorted(joined["players"], key=lambda p: p["p"])]
        per = -(-a.players // a.groups)
        centers, spots = clusters(sql(db, "SELECT * FROM lot", token), a.groups, a.radius, per)
        for cid, (x, y) in zip(ids, spots):
            call(db, "place_at", [cid, x, y], token)
        load.send("placed")
        ready = load.expect("ready", 900)
        held = [h["characters"] for h in ready["held"]]
        res["centers"] = centers
        res["held_at_ready"] = {"seen_characters_mean": round(sum(held) / len(held), 1), "min": min(held), "max": max(held)}
        load.send("go")
        time.sleep(a.warmup)
        call(db, "set_profile", [True], token)
        t0, b0 = time.time(), bytes_sent(ident)
        time.sleep(a.seconds)
        t1, b1 = time.time(), bytes_sent(ident)
        call(db, "set_profile", [False], token)
        # What each sampled player holds now, as that player.
        sample = []
        for p in players[:: max(1, a.players // a.sample)][: a.sample]:
            rows = sql(db, "SELECT * FROM seen_characters", p["token"])
            sample.append({"rows": len(rows), "bytes": sum(bsatn(r) for r in rows), "look_bytes": sum(4 + len(r.get("look", "").encode()) for r in rows if "look" in r),
                           "people_with_key": sum(1 for r in rows if r.get("kind") == "person" and r.get("look", "").startswith("lk_"))})
        load.send("stop")
        try:
            load.expect("done", 300)
        except RuntimeError:
            pass
        res["counts"] = {"projected": sql(db, "SELECT COUNT(*) AS n FROM projected", token)[0]["n"], "character": sql(db, "SELECT COUNT(*) AS n FROM character", token)[0]["n"]}
        try:
            res["counts"]["look"] = sql(db, "SELECT COUNT(*) AS n FROM look", token)[0]["n"]
        except RuntimeError:
            res["counts"]["look"] = None
        log = stdb("logs", "-s", "local", db, "-n", str(int((t1 - t0 + a.warmup + 60) * 60 * 12 + 50_000)), timeout=900)
        (out / "module.log").write_text(log)
        sp = spans(log, t0, t1)
        dur = t1 - t0
        res["window"] = {"t0": t0, "t1": t1, "seconds": round(dur, 1)}
        res["spans_ms_per_s"] = {k: round(sum(v) / dur, 2) for k, v in sorted(sp.items()) if k in ("tick", "tick.perception", "tick.frames", "housekeeping")}
        res["perception_ms_p50_p99"] = (lambda v: [round(v[len(v) // 2], 3), round(v[int(len(v) * 0.99)], 3)] if v else None)(sorted(sp.get("tick.perception", [])))
        res["bytes_sent_per_s"] = {k: round((b1.get(k, 0) - b0.get(k, 0)) / dur, 1) for k in sorted(set(b0) | set(b1))}
        res["bytes_sent_per_s_per_player"] = round(sum(b1.get(k, 0) - b0.get(k, 0) for k in b1) / dur / a.players, 1)
        res["seen_characters_sample"] = {"players": len(sample), "rows_mean": round(sum(s["rows"] for s in sample) / len(sample), 1),
                                         "bsatn_bytes_mean": round(sum(s["bytes"] for s in sample) / len(sample), 1),
                                         "look_column_bytes_mean": round(sum(s["look_bytes"] for s in sample) / len(sample), 1),
                                         "people_with_key_mean": round(sum(s["people_with_key"] for s in sample) / len(sample), 1)}
    finally:
        if load and load.p.poll() is None:
            load.p.terminate()
        stdb("delete", "-s", "local", db, "-y") if db.startswith("verify-lookcost-") else None
        (out / "result.json").write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
