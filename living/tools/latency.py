#!/usr/bin/env python3
"""One player's input latency with no added network delay, stage by stage (docs/LATENCY.md).

    latency.py up                       # own container (LAT_STDB_CONTAINER, default lat-stdb, port 3391)
    latency.py run [--label mac]        # publish a verify-lat-* island world, run the probe matrix, analyze
    latency.py analyze DIR              # re-analyze a run
    latency.py down                     # delete the run's databases, stop and remove the container and volume

`run` publishes a fresh `verify-lat-<stamp>` (seed island, the module from CARGO_TARGET_DIR) and
runs `latency-probe` (living/tools/latency_probe) once per configuration, each as a new player
identity and character: confirmed reads on/off x messages processed as they arrive (`thread`),
once per 60 Hz frame (`frame`, as the game client's `net::pump` did), or once per frame and again
right after each input (`flush`, as the game client's `net::flush` does since 2026-11-10). Server metrics are scraped
before and after each configuration. `--url` and `--container`/`--ssh` point it at another
server (the dev-box over the LAN); the probe always runs here, on this host's clock.

Clocks: client intervals (send -> reply, send -> row) use this host's clock only. Intervals that
cross to the server's `ReducerEvent.timestamp` use a clock offset bounded from the samples
themselves (t_send <= srv - off <= t_reply for every call), reported with its uncertainty.
"""

import argparse
import gzip
import json
import os
import re
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import world_delete  # noqa: E402  (pause a world before deleting it)

ROOT = Path(__file__).resolve().parents[2]
CONTAINER = os.environ.get("LAT_STDB_CONTAINER", "lat-stdb")
VOLUME = os.environ.get("LAT_STDB_VOLUME", "lat-stdb-data")
PORT = int(os.environ.get("LAT_STDB_PORT", "3391"))
IMAGE = "docker.io/clockworklabs/spacetime:v2.14.1"
TARGET = Path(os.environ.get("CARGO_TARGET_DIR", ROOT / "living/target"))
WASM_DIR = TARGET / "wasm32-unknown-unknown/release"
PROBE = TARGET / "release/latency-probe"
OUT = ROOT / ".local/living/latency"
FRAME_MS = 1000 / 60


def sh(*args, check=True, timeout=600, **kw):
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, **kw)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(map(str, args))[:200]}: {r.returncode} {r.stderr.strip()[-2000:]}")
    return r.stdout


class Server:
    def __init__(self, url, container, ssh=None):
        self.url, self.container, self.ssh = url, container, ssh

    def docker(self, *args, **kw):
        cmd = ["docker", *args]
        if self.ssh:
            cmd = ["ssh", self.ssh, " ".join(map(str, cmd))]
        return sh(*cmd, **kw)

    def stdb_run(self, *args):
        """The CLI as `stdb`, returning the completed process without raising (world_delete)."""
        if self.ssh:
            quoted = " ".join("'" + str(a).replace("'", "'\\''") + "'" for a in args)
            return subprocess.run(["ssh", self.ssh, f"docker exec -i {self.container} spacetime {quoted}"], capture_output=True, text=True, timeout=600)
        return subprocess.run(["docker", "exec", "-i", self.container, "spacetime", *args], capture_output=True, text=True, timeout=600)

    def stdb(self, *args, **kw):
        if self.ssh:
            quoted = " ".join("'" + str(a).replace("'", "'\\''") + "'" for a in args)
            return sh("ssh", self.ssh, f"docker exec -i {self.container} spacetime {quoted}", **kw)
        return sh("docker", "exec", "-i", self.container, "spacetime", *args, **kw)

    def http(self, path, body=None, token=None, raw=False, timeout=60):
        data = body.encode() if raw else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.url + path, data=data, method="POST" if data is not None or path == "/v1/identity" else "GET")
        if data is not None and not raw:
            req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def metrics(self):
        return urllib.request.urlopen(f"{self.url}/v1/metrics", timeout=30).read().decode().splitlines()

    def admin_token(self):
        found = re.findall(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", self.stdb("login", "show", "--token"))
        if len(found) != 1:
            raise RuntimeError("could not read the container CLI's token")
        return found[0]

    def sql(self, db, q, token):
        code, body = self.http(f"/v1/database/{db}/sql", q, token, raw=True)
        if code != 200:
            raise RuntimeError(f"sql {q!r}: {code} {body[:300]}")
        res = json.loads(body)[0]
        names = [e["name"]["some"] if isinstance(e["name"], dict) else e["name"] for e in res["schema"]["elements"]]
        return [dict(zip(names, r)) for r in res["rows"]]


def local_server():
    return Server(f"http://127.0.0.1:{PORT}", CONTAINER)


# ---- container ---------------------------------------------------------------------------------

def up(_a):
    if CONTAINER in sh("docker", "ps", "-a", "--format", "{{.Names}}").split():
        print(f"{CONTAINER} exists")
    else:
        sh("docker", "run", "-d", "--name", CONTAINER, "--stop-signal", "SIGINT", "-p", f"127.0.0.1:{PORT}:3000", "-v", f"{VOLUME}:/home/spacetime",
           "-v", f"{WASM_DIR}:/wasm:ro", IMAGE, "start", "--listen-addr", "0.0.0.0:3000")
    s = local_server()
    for _ in range(120):
        try:
            if s.http("/v1/ping", timeout=5)[0] == 200:
                print(f"{CONTAINER} answers on {s.url}")
                return
        except Exception:
            pass
        time.sleep(1)
    sys.exit("the server did not answer /v1/ping")


def down(_a):
    s = local_server()
    for f in sorted(OUT.glob("*/manifest.json")):
        m = json.loads(f.read_text())
        if m.get("container") == CONTAINER and m.get("url") == s.url:
            # Paused and read back as paused first (world_delete.py), on the server it runs on.
            print(m["db"], world_delete.cli_pause_and_delete(s.stdb_run, m["db"])[1])
    r = subprocess.run(["docker", "stop", "-t", "30", CONTAINER], capture_output=True, text=True)
    print("stop:", r.returncode, r.stderr.strip())
    subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True)
    subprocess.run(["docker", "volume", "rm", VOLUME], capture_output=True)
    print("container present:", CONTAINER in sh("docker", "ps", "-a", "--format", "{{.Names}}").split(),
          "volume present:", VOLUME in sh("docker", "volume", "ls", "--format", "{{.Name}}").split())


# ---- run ---------------------------------------------------------------------------------------

CONFIGS = [
    {"name": "confirmed-thread", "confirmed": True, "pump": "thread"},
    {"name": "unconfirmed-thread", "confirmed": False, "pump": "thread"},
    {"name": "confirmed-frame", "confirmed": True, "pump": "frame"},
    {"name": "unconfirmed-frame", "confirmed": False, "pump": "frame"},
    # The game client since 2026-11-10 (docs/LATENCY.md steps 1-2): unconfirmed, sent the frame it is made.
    {"name": "unconfirmed-flush", "confirmed": False, "pump": "flush"},
    {"name": "confirmed-flush", "confirmed": True, "pump": "flush"},
]


def ping_rtts(s, n=30):
    out = []
    for _ in range(n):
        t = time.perf_counter()
        s.http("/v1/ping", timeout=5)
        out.append((time.perf_counter() - t) * 1000)
    return out


def run(a):
    s = Server(a.url, a.container, a.ssh) if a.url else local_server()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    name = f"{a.label}-{stamp}"
    d = OUT / name
    d.mkdir(parents=True, exist_ok=True)
    db = a.db or f"verify-lat-{stamp}"
    if not db.startswith("verify-"):
        sys.exit("only verify-* scratch databases")
    if not a.db:
        s.stdb("publish", "-s", "local", "-b", a.wasm, db, "--delete-data", "-y")
        s.stdb("call", "-s", "local", db, "install_script", json.dumps((ROOT / "living/scripts/skills.rhai").read_text()))
    token = s.admin_token()
    git = os.environ.get("LAT_GIT") or sh("git", "-C", str(ROOT), "rev-parse", "HEAD", check=False).strip()
    dirty = sh("git", "-C", str(ROOT), "status", "--short", "--untracked-files=no", "living/authority", "living/rules", "living/scripts", check=False).splitlines()
    manifest = {"run": name, "db": db, "url": s.url, "container": s.container, "ssh": a.ssh, "git": git, "authority_dirty": dirty, "client_host": os.uname().nodename,
                "server_cli": s.stdb("--version").strip().splitlines()[-1], "configs": CONFIGS, "moves": a.moves, "move_ms": a.move_ms, "bolts": a.bolts, "bolt_ms": a.bolt_ms,
                "ping_ms": ping_rtts(s), "skill_cards": {c["skill"]: c for c in s.sql(db, "SELECT * FROM skill_card", token)},
                "world_rows": {t: len(s.sql(db, f"SELECT * FROM {t}", token)) for t in ("character", "body")}}
    (d / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"run {name}: db {db} at {s.url}; ping p50 {statistics.median(manifest['ping_ms']):.2f} ms; {manifest['world_rows']}")
    time.sleep(a.settle)
    for i, c in enumerate(CONFIGS):
        if a.only and c["name"] not in a.only:
            continue
        ptoken = json.loads(s.http("/v1/identity", {})[1])["token"]
        req = {"uri": s.url, "db": db, "token": ptoken, "name": f"Lat{i}", "out": str(d / f"{c['name']}.jsonl"), "confirmed": c["confirmed"], "pump": c["pump"],
               "moves": a.moves, "move_ms": a.move_ms, "bolts": a.bolts, "bolt_ms": a.bolt_ms}
        m0 = (time.time(), s.metrics())
        t = time.time()
        p = subprocess.run([str(PROBE)], input=json.dumps(req) + "\n", capture_output=True, text=True, timeout=1800)
        m1 = (time.time(), s.metrics())
        (d / f"{c['name']}.metrics.json").write_text(json.dumps({"t0": m0[0], "m0": m0[1], "t1": m1[0], "m1": m1[1]}))
        print(f"  {c['name']}: {time.time() - t:.0f} s, exit {p.returncode} {p.stdout.strip()[-200:]} {p.stderr.strip()[-500:]}")
    analyze_dir(d)


# ---- analysis ----------------------------------------------------------------------------------

def pct(xs, p):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * p / 100
    f = int(k)
    return xs[f] + (xs[min(f + 1, len(xs) - 1)] - xs[f]) * (k - f)


def summ(xs):
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "p50": round(pct(xs, 50), 2), "p95": round(pct(xs, 95), 2), "p99": round(pct(xs, 99), 2), "max": round(max(xs), 2), "min": round(min(xs), 2)}


def server_hists(mfile, reducers=("human_move", "use_skill", "tick")):
    """Bucket-bounded quantiles and means of the server's own histograms between the two scrapes."""
    m = json.loads(Path(mfile).read_text())

    def parse(lines):
        d = {}
        for l in lines:
            mm = re.match(r'^(\w+)\{([^}]*)\} (\S+)$', l)
            if mm:
                d[(mm.group(1), mm.group(2))] = float(mm.group(3))
        return d
    a, b = parse(m["m0"]), parse(m["m1"])
    lab = lambda labels, k: (re.search(rf'{k}="([^"]*)"', labels) or [None, None])[1]
    out = {}
    for hist in ("spacetime_reducer_wait_time_sec", "spacetime_reducer_plus_query_duration_sec", "spacetime_scheduled_function_delay_seconds"):
        per = {}
        sums = {}
        for (n, labels), v in b.items():
            red = lab(labels, "reducer") or lab(labels, "reducer_symbol") or lab(labels, "function")
            if red not in reducers:
                continue
            if n == hist + "_bucket":
                le = lab(labels, "le")
                per.setdefault(red, {})[float("inf") if le == "+Inf" else float(le)] = v - a.get((n, labels), 0)
            elif n == hist + "_sum":
                sums[red] = sums.get(red, 0) + v - a.get((n, labels), 0)
        res = {}
        for red, bk in per.items():
            items = sorted(bk.items())
            total = items[-1][1]
            if total <= 0:
                continue
            q = {}
            for p in (50, 95, 99):
                bound = next((le for le, c in items if c >= total * p / 100), float("inf"))
                q[f"p{p}_le_ms"] = bound * 1000 if bound != float("inf") else "inf"
            res[red] = {"count": int(total), "mean_ms": round(sums.get(red, 0) / total * 1000, 3), **q}
        out[hist] = res
    return out


def server_clock(bodies, frame_ms=FRAME_MS, fresh_only=False):
    """The game client's display clock, step by step: living/viewer/src/sync.rs `ServerClock` as
    living/game/src/bodies.rs drives it, with its constants (4 s window, 2% late share, 4 ms margin,
    10% slew, 1 s resync, 100 ms before the first row). Each 60 Hz frame takes the newest `t_ms`
    among body rows applied since the previous frame (net.rs `body_t.fetch_max`, inserts included)
    and records `t_ms - local`; the display shows authority time `local + off`.
    Frames run on a grid of this host's wall clock (ms); the real client's phase differs by < 1 frame.
    `fresh_only`: fed only by rows whose segment changed (not a body entering view, not a row whose
    `t_ms` is the one it replaces), as net.rs feeds it since 2026-11-10 (docs/LATENCY.md, step 3).
    Returns (frame times, off per frame)."""
    fresh = lambda b: not b.get("ins") and b.get("prev") is not None and b["prev"] != b["t"]
    arr = sorted((b["ts"] / 1000, b["t"]) for b in bodies if b["t"] and (not fresh_only or fresh(b)))
    if not arr:
        return [], []
    start = arr[0][0]
    times, offs = [], []
    off, synced, last = -100.0, False, None
    lags = []  # (local, lag)
    j = 0
    k = 0
    end = arr[-1][0] + 5000
    while True:
        now = start + k * frame_ms
        if now > end:
            break
        latest = 0
        while j < len(arr) and arr[j][0] <= now:
            latest = max(latest, arr[j][1])
            j += 1
        dt = 0.0 if last is None else now - last
        last = now
        if latest:
            lags.append((now, latest - now))
        while lags and now - lags[0][0] > 4000.0:
            lags.pop(0)
        if lags:
            vals = sorted(l for _, l in lags)
            kk = min(int(len(vals) * 0.02), len(vals) - 1)
            target = vals[kk] - 4.0
            gap = target - off
            if not synced or abs(gap) > 1000.0:
                off, synced = target, True
            else:
                off += max(-0.1 * dt, min(0.1 * dt, gap))
        times.append(now)
        offs.append(off)
        k += 1
    return times, offs


def offset_bounds(pairs):
    """pairs: (t_send_us, srv_us, t_reply_us). The server clock minus this one, bounded so that
    every call was received after it was sent and before its reply arrived."""
    lo = max(srv - tr for ts, srv, tr in pairs)  # srv - off <= tr  ->  off >= srv - tr
    hi = min(srv - ts for ts, srv, tr in pairs)  # srv - off >= ts  ->  off <= srv - ts
    return lo, hi


def windowed_offsets(pairs, span_us=10e6):
    """Per call, the offset bounded by the calls within +-10 s (the Docker Desktop VM's clock
    drifts against macOS by milliseconds over a run). Returns {t_send: (mid, half_width)}."""
    pairs = sorted(pairs)
    out = {}
    import bisect
    keys = [p[0] for p in pairs]
    for p in pairs:
        w = pairs[bisect.bisect_left(keys, p[0] - span_us):bisect.bisect_right(keys, p[0] + span_us)]
        lo, hi = offset_bounds(w)
        out[p[0]] = ((lo + hi) / 2, (hi - lo) / 2)
    return out


def analyze_config(path, cards, same_clock=False):
    path = Path(path)
    text = gzip.decompress(path.read_bytes()).decode() if path.suffix == ".gz" else path.read_text()
    ev = [json.loads(l) for l in text.splitlines() if l.strip()]
    ins = {e["n"]: e for e in ev if e["k"] == "in"}
    res = {e["n"]: e for e in ev if e["k"] == "res"}
    bodies = [e for e in ev if e["k"] == "b"]
    mine = [e for e in bodies if e["me"]]
    uses = [e for e in ev if e["k"] == "use"]
    out = {}
    pairs = [(ins[n]["ts"], res[n]["srv"], res[n]["ts"]) for n in res if n in ins]
    lo, hi = offset_bounds(pairs)
    win = windowed_offsets(pairs)
    if same_clock:  # client and server read one kernel clock (the dev-box's own container)
        win = {k: (0.0, 0.0) for k in win}
    halfw = [h for _, h in win.values()]
    out["clock_offset_us"] = {"whole_run_lo": lo, "whole_run_hi": hi, "whole_run_half_width_ms": round((hi - lo) / 2000, 3),
                              "windowed_half_width_ms": summ([h / 1000 for h in halfw])}
    offat = lambda ts: win[ts][0]
    # Moves.
    mv = []
    my_by_srv = {}
    for b in mine:
        if b.get("srv") is not None:
            my_by_srv.setdefault(b["srv"], b)
    for n, i in ins.items():
        if i["r"] != "move" or n not in res or res[n]["st"] != "ok":
            continue
        r = res[n]
        off = offat(i["ts"])
        row = my_by_srv.get(r["srv"])
        mv.append({"send_to_receipt": (r["srv"] - off - i["ts"]) / 1000, "receipt_to_reply": (r["ts"] - (r["srv"] - off)) / 1000, "send_to_reply": (r["ts"] - i["ts"]) / 1000,
                   "row_lag": (row["ts"] - (row["t"] * 1000 + off)) / 1000 if row else None, "seg_t_minus_receipt_ms": (row["t"] * 1000 - r["srv"]) / 1000 if row else None,
                   "send_us": i["ts"], "row": row})
    # The game's display clock, emulated: when my new segment's start is first drawn.
    import bisect
    times, offs = server_clock(bodies)
    for m in mv:
        if not m["row"] or not times:
            continue
        arrival = m["row"]["ts"] / 1000
        f = bisect.bisect_left(times, arrival)
        while f < len(times) and times[f] + offs[f] < m["row"]["t"]:
            f += 1
        if f >= len(times):
            continue
        m["applied_frame_wait"] = times[bisect.bisect_left(times, arrival)] - arrival if bisect.bisect_left(times, arrival) < len(times) else None
        m["display_wait"] = times[f] - arrival
        m["send_to_drawn_start"] = times[f] - m["send_us"] / 1000
    # Since 2026-11-10 my own body is drawn from its newest segment in the frame that applies it
    # (bodies.rs `mine_at`): with a pump per frame, the row's callback time is that frame.
    pump = next((e.get("pump") for e in ev if e["k"] == "joined"), "frame")
    for m in mv:
        if not m["row"]:
            continue
        arrival = m["row"]["ts"] / 1000
        if pump == "thread":
            f = bisect.bisect_left(times, arrival)
            applied = times[f] if f < len(times) else None
        else:
            applied = arrival
        if applied is not None:
            m["send_to_drawn_own"] = applied - m["send_us"] / 1000
    out["moves"] = {k: summ([m[k] for m in mv if m.get(k) is not None]) for k in ("send_to_receipt", "receipt_to_reply", "send_to_reply", "row_lag", "seg_t_minus_receipt_ms",
                                                                                "display_wait", "send_to_drawn_start", "send_to_drawn_own")}
    # How far the display runs behind each frame's newest fresh row: local - (local + off) = -off, minus the authority-to-local offset.
    out["display_behind_local_ms"] = summ([-o for o in offs[len(offs) // 20:]])
    # The same clock fed only by changed segments (net.rs since 2026-11-10): what others are drawn at.
    _, offs_fresh = server_clock(bodies, fresh_only=True)
    out["display_behind_local_ms_fresh_rows"] = summ([-o for o in offs_fresh[len(offs_fresh) // 20:]])
    jumps = lambda o: sum(1 for a, b in zip(o, o[1:]) if abs(b - a) > 500)
    out["display_resyncs"] = {"all_rows": jumps(offs), "fresh_rows": jumps(offs_fresh)}
    rows = sorted((b["ts"] / 1000, b["t"]) for b in bodies if b["t"])
    stale = [1 for ts, t in rows if ts - t > 300]
    out["body_rows"] = {"n": len(rows), "older_than_300ms_at_arrival": len(stale)}
    out["moves"]["refused"] = sum(1 for n, i in ins.items() if i["r"] == "move" and n in res and res[n]["st"] != "ok")
    out["moves"]["unanswered"] = sum(1 for n, i in ins.items() if i["r"] == "move" and n not in res)
    off = sum(o for o, _ in win.values()) / len(win)
    # Skills.
    st = {}
    for u in uses:
        st.setdefault(u["use"], []).append(u)
    sk = []
    for n, i in ins.items():
        if i["r"] != "skill" or n not in res:
            continue
        r = res[n]
        at = r["srv"] // 1000
        cand = [k for k, v in st.items() if any(x["at"] == at and x["src"] == "player" for x in v)]
        rec = {"send_to_reply": (r["ts"] - i["ts"]) / 1000, "status": r["st"]}
        if cand:
            states = st[cand[-1]]
            card = cards.get(states[0]["skill"], {})
            w = card.get("windup_ms", 0)
            acc = next((x for x in states if x["acc"]), None)
            rel = next((x for x in states if x["rel"]), None)
            outc = next((x for x in states if x["out"]), None)
            rec["outcome"] = outc["out"] if outc else None
            if acc:
                rec["accepted_after_receipt_ms"] = acc["acc"] - at
                rec["send_to_accepted_arrival"] = (acc["ts"] - i["ts"]) / 1000
            if rel and acc:
                rec["release_minus_windup_authority_ms"] = rel["rel"] - acc["acc"] - w
                rec["release_after_tick_arrival"] = (rel["ts"] - (rel["rel"] * 1000 + off)) / 1000
                rec["send_to_release_arrival_minus_windup"] = (rel["ts"] - i["ts"]) / 1000 - w
        sk.append(rec)
    out["skills"] = {k: summ([s[k] for s in sk if s.get(k) is not None]) for k in ("send_to_reply", "accepted_after_receipt_ms", "send_to_accepted_arrival", "release_minus_windup_authority_ms",
                                                                                     "release_after_tick_arrival", "send_to_release_arrival_minus_windup")}
    out["skills"]["outcomes"] = {}
    for s_ in sk:
        k = (s_.get("outcome") or s_["status"])[:60]
        out["skills"]["outcomes"][k] = out["skills"]["outcomes"].get(k, 0) + 1
    return out


def analyze_dir(d, same_clock=False):
    d = Path(d)
    man = json.loads((d / "manifest.json").read_text())
    rep = {"run": man["run"], "ping_ms": summ(man["ping_ms"]), "same_clock": same_clock}
    for c in CONFIGS:
        p = d / f"{c['name']}.jsonl"
        if not p.exists():
            p = p.with_suffix(".jsonl.gz")
        if not p.exists():
            continue
        r = analyze_config(p, man["skill_cards"], same_clock)
        mf = d / f"{c['name']}.metrics.json"
        if mf.exists():
            r["server"] = server_hists(mf)
        rep[c["name"]] = r
    (d / "report.json").write_text(json.dumps(rep, indent=2))
    print_table(rep)


def print_table(rep):
    print(rep["run"], "ping", rep["ping_ms"])
    for c in CONFIGS:
        x = rep.get(c["name"])
        if not x:
            continue
        print(f"== {c['name']}  offset half-width ms (windowed) {x['clock_offset_us']['windowed_half_width_ms']}  display behind {x['display_behind_local_ms']}  rows {x['body_rows']}")
        if "display_behind_local_ms_fresh_rows" in x:
            print(f"   display behind, fed by changed segments only: {x['display_behind_local_ms_fresh_rows']}  resyncs {x.get('display_resyncs')}")
        for sec in ("moves", "skills"):
            for k, v in x[sec].items():
                if isinstance(v, dict) and v.get("n"):
                    print(f"  {sec}.{k:40s} n={v['n']:4d} p50={v['p50']:8.2f} p95={v['p95']:8.2f} p99={v['p99']:8.2f} max={v['max']:8.2f}")
                elif not isinstance(v, dict) or k == "outcomes":
                    print(f"  {sec}.{k}: {v}")
        for h, dd in x.get("server", {}).items():
            for red, v in dd.items():
                print(f"  server {h.removeprefix('spacetime_')} {red}: {v}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("up")
    sub.add_parser("down")
    r = sub.add_parser("run")
    r.add_argument("--label", default="mac")
    r.add_argument("--url")
    r.add_argument("--container", default=CONTAINER)
    r.add_argument("--ssh", help="run the server's CLI over ssh (the dev-box)")
    r.add_argument("--wasm", default="/wasm/living_authority.wasm", help="the module's path inside the container")
    r.add_argument("--db")
    r.add_argument("--moves", type=int, default=200)
    r.add_argument("--move-ms", type=int, default=300)
    r.add_argument("--bolts", type=int, default=15)
    r.add_argument("--bolt-ms", type=int, default=4300)
    r.add_argument("--settle", type=int, default=10)
    r.add_argument("--only", nargs="*")
    an = sub.add_parser("analyze")
    an.add_argument("dir")
    an.add_argument("--same-clock", action="store_true", help="client and server share one kernel clock: server minus client offset is 0")
    a = ap.parse_args()
    {"up": up, "down": down, "run": run, "analyze": lambda a: analyze_dir(a.dir, a.same_clock)}[a.cmd](a)


if __name__ == "__main__":
    main()
