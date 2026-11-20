#!/usr/bin/env python3
"""Exact comparison of two authority builds on one battle, tick by tick (docs/COMBAT_PHASE.md,
"Step 3 results"). Python standard library and docker.

    det_compare.py prepare --container A --url http://127.0.0.1:PA --volume VOL_A --wasm-dir DIR \
                   --base BASE.wasm --template TEMPLATE_VOLUME [--fighters 200] [--ticks 3600]
    det_compare.py delete --container A --db verify-det-<stamp>
    det_compare.py run --template TEMPLATE_VOLUME --wasm-dir DIR --base BASE.wasm \
                   --candidate CAND.wasm --ports PX,PY --out DIR

Both wasm files sit in `DIR` (mounted at `/wasm`), and both builds carry the `det_clock` law
(living/authority/src/det.rs).

`prepare` publishes the base build fresh on server A as `verify-det-<stamp>`, waits for genesis,
pauses, stages the battle (`spawn_battle`) and sets the laws `det_clock` (the clock, the random
draws and housekeeping follow the tick count alone) and `det_stop` (pause after `--ticks` ticks).
Then it stops server A cleanly (SIGINT), copies its whole volume into the template volume, starts
server A again and writes `<template>.json` beside nothing but the volume's name (printed).

`run` copies the template into two new volumes and starts a server on each, the same way (a
server resumes its sequences differently after a restart, so the two copies are treated alike).
On one it publishes the base, on the other the candidate, each as an update with the data kept
(a fresh module instance on both); unpauses both; waits until `det_stop` pauses each; then
compares each tick's `det tick` line (a hash of every table's rows as a multiset) from both
replicas' whole module logs, and every table's rows read through SQL at the stop. Writes
`<out>/det-compare.json`; exit 0 only when every tick and every table is identical. The two
copies' containers and volumes are removed at the end (by their exact names).
"""
import argparse
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

IMAGE = "clockworklabs/spacetime:v2.14.1"
REPLICAS = "/home/spacetime/.local/share/spacetime/data/replicas"
# Tables read at the stop: every table the det trace hashes, and the clock (its tick).
TABLES = """mind_cursor world look sex sex_seen look_line gate routine routine_stat background world_law law_override
law_revision cover_law cover_ground land_plan settlement lot character body steer walk_route vitals
activity inventory resource_node structure rot brain mind_state wake infant_cry audience experience
line_heard speech_card know_how artifact far_handle known_ground remembered ground_edit familiar
last_look seen_structures mind_cursor fast_ask slumber heard_asleep deliberation persona relation
belief judged cue judgment seen_stock standing place thought chronicle bond_offer community
membership join_request trade_offer expecting rearing act_queue genome practice pasture skill_card
fighter combat_seen fight_seen missile skill_use readiness character_senses character_earshot
act_outcome weather skill_code act_card doing perceived heard knowledge_epoch hear_salt law_change
projected fighter_seen player motion_seen line_seen doing_seen motion_near fighter_near doing_near
seen_body_copy copy_state seen_character_copy reveal acquaintance rhythm guest attention applied_gaze
record record_party record_clock genesis""".split()


class Server:
    def __init__(self, container, url):
        self.c, self.url = container, url.rstrip("/")
        self._token = None

    def cli(self, *args, timeout=900):
        r = subprocess.run(["docker", "exec", self.c, "spacetime", *args], capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            raise RuntimeError(f"spacetime {' '.join(args)}: {r.stderr[-800:]}")
        return r.stdout + r.stderr

    def token(self):
        if not self._token:
            found = re.findall(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", self.cli("login", "show", "--token"))
            assert len(found) == 1, "the container CLI's token"
            self._token = found[0]
        return self._token

    def http(self, path, body=None, raw=False):
        data = body.encode() if raw else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.url + path, data=data, method="POST" if data is not None else "GET")
        req.add_header("Authorization", f"Bearer {self.token()}")
        req.add_header("Content-Type", "text/plain" if raw else "application/json")
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def sql(self, db, q):
        code, body = self.http(f"/v1/database/{db}/sql", q, raw=True)
        if code != 200:
            raise RuntimeError(f"sql {q!r}: {code} {body[:300]}")
        res = json.loads(body)[0]
        names = [e["name"]["some"] if isinstance(e["name"], dict) else e["name"] for e in res["schema"]["elements"]]
        return [dict(zip(names, r)) for r in res["rows"]]

    def call(self, db, reducer, args):
        code, body = self.http(f"/v1/database/{db}/call/{reducer}", args)
        if code != 200:
            raise RuntimeError(f"{reducer}{args}: {code} {body[:300]}")

    def ping(self, seconds=180):
        end = time.time() + seconds
        while time.time() < end:
            try:
                with urllib.request.urlopen(self.url + "/v1/ping", timeout=5) as r:
                    if r.status == 200:
                        return
            except OSError:
                pass
            time.sleep(1)
        raise RuntimeError(f"{self.c} does not answer at {self.url}")

    def replica_log(self, replica):
        d = f"{REPLICAS}/{replica}/module_logs"
        r = subprocess.run(["docker", "exec", self.c, "sh", "-c", f"cat $(ls -1 {d}/* | sort)"], capture_output=True, timeout=900)
        return r.stdout.decode("utf-8", "replace")

    def det_replica(self, stop):
        """The replica whose module log says it paused at `stop` (`det tick <stop>: paused`): the
        world compared (a server may hold older replicas' logs)."""
        r = subprocess.run(["docker", "exec", self.c, "sh", "-c", f"grep -l 'det tick {stop}: paused' {REPLICAS}/*/module_logs/* | head -1"], capture_output=True, text=True, timeout=600)
        m = re.search(r"/replicas/(\d+)/", r.stdout)
        return int(m.group(1)) if m else None

    def newest_replica(self):
        r = subprocess.run(["docker", "exec", self.c, "sh", "-c", f"ls -1 {REPLICAS}"], capture_output=True, text=True, timeout=60)
        return max(int(x) for x in r.stdout.split() if x.isdigit())


def det_ticks(log):
    """Each `det tick N all=H t=h/n …` line of a replica's JSON-lines module log: {N: (all, {t: h/n})}."""
    out = {}
    for line in log.splitlines():
        try:
            msg = json.loads(line).get("message", "")
        except ValueError:
            continue
        m = re.match(r"det tick (\d+) all=([0-9a-f]+) (.*)$", msg)
        if m:
            out[int(m.group(1))] = (m.group(2), dict(kv.split("=", 1) for kv in m.group(3).split()))
    return out


# Auto-increment tables: SpacetimeDB 2.14.1 skips a sequence ahead to its next block of 4,096 at
# random (seeded from the operating system at each database load), so the same rows get other ids
# on two servers. Rows are compared with each such id by its rank among its table's ids, and the
# references the battle writes renamed alike, as `det.rs` hashes them.
AUTO_INC = """acquaintance act_queue artifact audience belief bond_offer character chronicle combat_seen
community cue expecting experience familiar far_handle fight_seen ground_edit guest heard_asleep
inventory join_request judged judgment know_how known_ground law_change look_line membership missile
perceived place practice projected record_party record relation remembered reveal routine seen_stock
seen_structures sex_seen skill_use structure thought trade_offer""".split()
FAR_BASE = 1_000_000_000
STRUCTURE_BIT, FAM_STRUCTURE, KIND_MASK = 1 << 40, 3 << 40, 7 << 40


def normalized(rows):
    import bisect
    ids = {t: sorted(r["id"] for r in rows[t]) for t in AUTO_INC if t in rows}

    def rank(t, i):
        v = ids[t]
        k = bisect.bisect_left(v, i)
        return k if k < len(v) and v[k] == i else (1 << 40) | k

    def far(n):
        return FAR_BASE + (rank("far_handle", n - FAR_BASE) & 0x0FFFFFFF) if isinstance(n, int) and FAR_BASE <= n < 2**32 else n

    def text(x):
        return re.sub(r"#(\d{10})(?!\d)", lambda m: "#%010d" % far(int(m.group(1))) if FAR_BASE <= int(m.group(1)) < 2**32 else m.group(0), x)

    def skey(k, bit):
        return bit | (rank("structure", k & (STRUCTURE_BIT - 1)) & (STRUCTURE_BIT - 1)) if k & KIND_MASK == bit else k

    def deep(v):
        if isinstance(v, str):
            return text(v)
        if isinstance(v, list):
            return [deep(x) for x in v]
        if isinstance(v, dict):
            return {k: deep(x) for k, x in v.items()}
        return v

    out = {}
    for t, rs in rows.items():
        new = []
        for r in rs:
            r = deep(dict(r))
            if t in AUTO_INC:
                r["id"] = rank(t, r["id"])
            if t == "experience":
                r["subject"], r["object"] = far(r["subject"]), far(r["object"])
            elif t == "inventory":
                r["owner"] = skey(r["owner"], STRUCTURE_BIT)
            elif t == "rot":
                r["structure"] = rank("structure", r["structure"])
            elif t == "familiar":
                r["thing"] = skey(r["thing"], FAM_STRUCTURE)
            elif t == "line_heard":
                r["line"] = rank("experience", r["line"])
            elif t == "missile":
                r["use_id"] = rank("skill_use", r["use_id"])
            new.append(r)
        out[t] = new
    return out


def wait_paused(s, db, seconds):
    end = time.time() + seconds
    while time.time() < end:
        if s.sql(db, "SELECT paused FROM world")[0]["paused"]:
            return True
        time.sleep(5)
    return False


def copy_volume(src, dst):
    subprocess.run(["docker", "volume", "create", dst], check=True, capture_output=True)
    subprocess.run(["docker", "run", "--rm", "--user", "0", "-v", f"{src}:/from:ro", "-v", f"{dst}:/to", "--entrypoint", "sh", IMAGE, "-c", "cp -a /from/. /to/"], check=True, timeout=1800)


def prepare(a):
    import genesis_wait
    A = Server(a.container, a.url)
    stamp = time.strftime("%m%d-%H%M%S")
    db = f"verify-det-{stamp}"
    print(f"det_compare: publishing {db}", flush=True)
    A.cli("publish", "-s", "local", "-b", f"/wasm/{a.base}", db, "--delete-data", "-y")
    for attempt in range(10):
        try:
            genesis_wait.wait_ready(A.url, db, A.token())
            break
        except OSError:
            # A busy server sometimes resets a connection right after a publish.
            if attempt == 9:
                raise
            time.sleep(5)
    A.call(db, "set_paused", [True])
    A.call(db, "spawn_battle", [a.fighters])
    if a.players:
        # Players watching (exact items): `a.players` fresh identities joined over HTTP (no
        # connection: their characters are human by controller, so the sweeps and frames run for
        # them) and placed over the ring `--ring LO,HI` m round the battle's centre (the arrival
        # less 20 m, as spawn_battle and battle_viewers.py take it). Without a connection a
        # character is taken over by a mind after `takeover_s` (30 s): keep `--ticks` under it.
        import math
        land = A.sql(db, "SELECT * FROM land")
        site = (land[0]["arrive_x"], land[0]["arrive_y"] - 20.0) if land else (55.0, 60.0)
        lo, hi = (float(x) for x in a.ring.split(","))
        before = {r["id"] for r in A.sql(db, "SELECT id FROM character")}
        for i in range(a.players):
            token = json.loads(urllib.request.urlopen(urllib.request.Request(f"{A.url}/v1/identity", data=b"", method="POST"), timeout=60).read())["token"]
            req = urllib.request.Request(f"{A.url}/v1/database/{db}/call/join", data=json.dumps([f"Watch{i}"]).encode(), method="POST",
                                         headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=60).read()
        joined = sorted(r["id"] for r in A.sql(db, "SELECT id FROM character") if r["id"] not in before and r["id"])
        n = len(joined)
        for i, cid in enumerate(joined):
            ang, rr = i * 2.399963, (lo * lo + (hi * hi - lo * lo) * ((i + 0.5) / max(1, n))) ** 0.5
            A.call(db, "place_at", [cid, site[0] + rr * math.cos(ang), site[1] + rr * math.sin(ang)])
        print(f"det_compare: {n} players joined and placed on the {lo:g}-{hi:g} m ring", flush=True)
    t0 = A.sql(db, "SELECT tick FROM clock")[0]["tick"]
    A.call(db, "set_world_law", ["det_clock", "true"])
    A.call(db, "set_world_law", ["det_stop", str(float(t0 + a.ticks))])
    meta = {"db": db, "start_tick": t0, "stop_tick": t0 + a.ticks, "fighters": a.fighters, "players": a.players, "ring": a.ring, "ticks": a.ticks, "replica": A.newest_replica(), "made_with": a.base}
    print(f"det_compare: {db} paused at tick {t0}, battle of {a.fighters}, stop at {t0 + a.ticks}", flush=True)
    subprocess.run(["docker", "kill", "-s", "INT", a.container], check=True, capture_output=True)
    subprocess.run(["docker", "wait", a.container], check=True, capture_output=True, timeout=300)
    copy_volume(a.volume, a.template)
    subprocess.run(["docker", "start", a.container], check=True, capture_output=True)
    A.ping()
    Path(a.meta).write_text(json.dumps(meta, indent=1) + "\n")
    print(json.dumps(meta), flush=True)
    return 0


def run(a):
    meta = json.loads(Path(a.meta).read_text())
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    db, t0, ticks, replica = meta["db"], meta["start_tick"], meta["ticks"], meta["replica"]
    res = {**meta, "base": a.base, "candidate": a.candidate}
    ports = [int(p) for p in a.ports.split(",")]
    names = [f"{a.template}-x{a.tag}", f"{a.template}-y{a.tag}"]
    try:
        servers = []
        for name, port in zip(names, ports):
            copy_volume(a.template, name)
            # `--cpus ""` leaves the copies unpinned (a host whose rootless cgroups have no cpuset
            # controller delegated, as the dev-box's podman).
            pin = ["--cpuset-cpus", a.cpus] if a.cpus else []
            subprocess.run(["docker", "run", "-d", "--name", name, *pin, "--ulimit", "nofile=65536:524288", "-p", f"127.0.0.1:{port}:3000",
                            "-v", f"{a.wasm_dir}:/wasm", "-v", f"{name}:/home/spacetime", IMAGE, "start", "--listen-addr", "0.0.0.0:3000"], check=True, capture_output=True)
            servers.append(Server(name, f"http://127.0.0.1:{port}"))
        for s in servers:
            s.ping()
        X, Y = servers
        X.cli("publish", "-s", "local", "-b", f"/wasm/{a.base}", db, "-y")
        Y.cli("publish", "-s", "local", "-b", f"/wasm/{a.candidate}", db, "-y")
        for s in servers:
            assert s.sql(db, "SELECT tick FROM clock")[0]["tick"] == t0, "both copies at the start tick"
        if a.stop:
            # An earlier stop (a tick number): both copies pause there, for a full read of that tick.
            ticks = a.stop - t0
            res["stop_tick"], res["ticks"] = a.stop, ticks
            for s in servers:
                s.call(db, "set_world_law", ["det_stop", str(float(a.stop))])
        for s in servers:
            s.call(db, "set_paused", [False])
        t_run = time.time()
        for s in servers:
            if not wait_paused(s, db, 7200):
                raise RuntimeError(f"{s.c} did not reach det_stop")
        res["run_s"] = round(time.time() - t_run, 1)
        time.sleep(15)
        replica = X.det_replica(t0 + ticks)
        if replica is None:
            raise RuntimeError('no replica log says it paused at det_stop')
        res["replica"] = replica
        la, lb = det_ticks(X.replica_log(replica)), det_ticks(Y.replica_log(replica))
        rng = range(t0 + 1, t0 + ticks + 1)
        missing = {"base": [t for t in rng if t not in la], "candidate": [t for t in rng if t not in lb]}
        differ = []
        for t in rng:
            if t in la and t in lb and la[t][0] != lb[t][0]:
                ta, tb = la[t][1], lb[t][1]
                differ.append({"tick": t, "tables": {k: [ta.get(k), tb.get(k)] for k in sorted(set(ta) | set(tb)) if ta.get(k) != tb.get(k)}})
        res["ticks_compared"] = sum(1 for t in rng if t in la and t in lb)
        res["ticks_missing"] = {k: len(v) for k, v in missing.items()}
        res["ticks_differ"] = len(differ)
        res["first_differences"] = differ[:20]
        rows_a = {t: X.sql(db, f"SELECT * FROM {t}") for t in TABLES + ["clock"]}
        rows_b = {t: Y.sql(db, f"SELECT * FROM {t}") for t in TABLES + ["clock"]}
        key = lambda r: json.dumps(r, sort_keys=True)
        tables_differ = {}
        na, nb = normalized(rows_a), normalized(rows_b)
        for t in TABLES:
            ka, kb = sorted(map(key, na[t])), sorted(map(key, nb[t]))
            if ka != kb:
                sa, sb = set(ka), set(kb)
                tables_differ[t] = {"base_rows": len(ka), "candidate_rows": len(kb), "only_base": [x[:1500] for x in ka if x not in sb][:20], "only_candidate": [x[:1500] for x in kb if x not in sa][:20]}
        res["tables_compared"] = len(TABLES)
        res["rows_compared"] = sum(len(v) for k, v in rows_a.items() if k != "clock")
        res["tables_differ"] = tables_differ
        res["stop_clock"] = {"base": rows_a["clock"][0].get("tick"), "candidate": rows_b["clock"][0].get("tick")}
        last = {"base": la.get(t0 + ticks, (None, {}))[1], "candidate": lb.get(t0 + ticks, (None, {}))[1]}
        res["last_tick_rows"] = {k: {t: v[t].split("/")[1] for t in ("character", "activity", "experience", "act_outcome", "combat_seen", "chronicle") if t in v} for k, v in last.items()}
        res["alive_at_stop"] = sum(1 for r in rows_a["character"] if r.get("alive"))
        res["identical"] = not differ and not tables_differ and not any(missing.values())
        (out / "det-compare.json").write_text(json.dumps(res, indent=1) + "\n")
        (out / "det-base.log").write_text("\n".join(f"{t} {la[t][0]}" for t in sorted(la)) + "\n")
        (out / "det-candidate.log").write_text("\n".join(f"{t} {lb[t][0]}" for t in sorted(lb)) + "\n")
        print(json.dumps({k: res[k] for k in ("identical", "ticks_compared", "ticks_differ", "ticks_missing", "tables_compared", "rows_compared", "run_s", "alive_at_stop")}), flush=True)
        return 0 if res["identical"] else 1
    finally:
        if not a.keep_copies:
            for name in names:
                subprocess.run(["docker", "rm", "-f", name], capture_output=True)
                subprocess.run(["docker", "volume", "rm", name], capture_output=True)


def delete(a):
    """Delete a `verify-det-*` world on server A only after it reads back paused (world_delete.py)."""
    if not a.db.startswith("verify-det-"):
        raise SystemExit(f"refusing to delete {a.db}: not a verify-det- database")
    import world_delete
    cli = lambda *args: subprocess.run(["docker", "exec", "-i", a.container, "spacetime", *args], capture_output=True, text=True, timeout=600)
    deleted, why = world_delete.cli_pause_and_delete(cli, a.db)
    print(f"delete {a.db}: {why}", flush=True)
    return 0 if deleted else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["prepare", "run", "delete"])
    ap.add_argument("--db", help="delete: the verify-det-* world on server A")
    ap.add_argument("--container")
    ap.add_argument("--url")
    ap.add_argument("--volume", help="server A's volume (mounted at /home/spacetime)")
    ap.add_argument("--wasm-dir", help="the host directory mounted at /wasm")
    ap.add_argument("--template", help="the template volume (prepare writes it, run copies it)")
    ap.add_argument("--meta", help="the template's JSON record (prepare writes it, run reads it)")
    ap.add_argument("--base")
    ap.add_argument("--candidate")
    ap.add_argument("--fighters", type=int, default=200)
    ap.add_argument("--ticks", type=int, default=3600)
    ap.add_argument("--players", type=int, default=0, help="prepare: players joined (no connection) and placed on --ring round the battle (exact items)")
    ap.add_argument("--ring", default="10,10", help="prepare: the players' ring LO,HI m from the battle's centre")
    ap.add_argument("--ports", default=None, help="run: the two copies' ports, PX,PY")
    ap.add_argument("--out")
    ap.add_argument("--keep-copies", action="store_true")
    ap.add_argument("--tag", default="", help="run: a suffix for the copies' names (two runs at once)")
    ap.add_argument("--stop", type=int, default=0, help="run: pause both copies at this tick instead of the template's det_stop")
    ap.add_argument("--cpus", default="0-4,10-14", help="run: the copies' cores (default the Spark's A725 cores, away from pinned measurements)")
    a = ap.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    return {"prepare": prepare, "run": run, "delete": delete}[a.step](a)


if __name__ == "__main__":
    sys.exit(main())
