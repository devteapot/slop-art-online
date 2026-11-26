#!/usr/bin/env python3
"""Exact comparison of two authority builds on one battle, tick by tick (docs/COMBAT_PHASE.md,
"Step 3 results"). Python standard library and docker.

    det_compare.py prepare --container A --url http://127.0.0.1:PA --volume VOL_A --wasm-dir DIR \
                   --base BASE.wasm --template TEMPLATE_VOLUME [--fighters 200] [--ticks 3600] \
                   [--sides 2 [--layout-seed S [--deal 1]]]
    det_compare.py delete --container A --db verify-det-<stamp>
    det_compare.py run --template TEMPLATE_VOLUME --wasm-dir DIR --base BASE.wasm \
                   --candidate CAND.wasm --ports PX,PY --out DIR

Both wasm files sit in `DIR` (mounted at `/wasm`), and both builds carry the `det_clock` law
(living/authority/src/det.rs).

With players (`prepare --players N --ring LO,HI`: joined with no connection, placed round the
battle), the sweeps and frames run too. Their rows are hashed by content with ids by rank
(det.rs: `act_outcome`, `line_seen`, `seen_character_copy`), and the hearing salt is a constant
under `det_clock`, so main against itself is identical. `run --cpus ""` runs the copies unpinned
(the dev-box's rootless podman has no cpuset controller); the output records `pinned`.

`prepare` publishes the base build fresh on server A as `verify-det-<stamp>`, waits for genesis,
pauses, stages the battle (`spawn_battle`) and sets the laws `det_clock` (the clock, the random
draws and housekeeping follow the tick count alone) and `det_stop` (pause after `--ticks` ticks).
Then it stops server A cleanly (SIGINT), copies its whole volume into the template volume, starts
server A again and writes `<template>.json` beside nothing but the volume's name (printed).

`run --candidate-law NAME=VALUE` sets a law on the candidate copy alone before both unpause (a
negative control; the law must be one the template's installed script has). `run --scripts
BASE.rhai,CAND.rhai [--seed NAME]` installs each build's own shipped script (with the seed's laws
composed over it, as `install_script.py --seed` does) on its copy before both unpause, as `just
living-publish` does after an update: the template keeps the script of the build that made it, so
without this a candidate whose change is in the script's defaults runs the template's. The
`script` row and the clock's script revision are not hashed or compared. Acts sent from
outside cannot be compared this way: a reducer called from outside the tick takes the wall clock
as its time (`common::now_ms`), which differs between the copies.

`run` copies the template into two new volumes and starts a server on each, the same way (a
server resumes its sequences differently after a restart, so the two copies are treated alike).
On one it publishes the base, on the other the candidate, each as an update with the data kept
(a fresh module instance on both); unpauses both; waits until `det_stop` pauses each; then
compares each tick's `det tick` line (a hash of every table's rows as a multiset) from both
replicas' whole module logs, and every table's rows read through SQL at the stop. Writes
`<out>/det-compare.json`; exit 0 only when every tick and every table is identical. The two
copies' containers and volumes are removed at the end (by their exact names).

Deliberation scene IDs are ranked in their table's namespace, including character references,
far handles, structures, resource nodes and trade offers. The comparison preserves references
and scene content. The authority trace and final SQL comparison both apply the rule. Build both
WASMs with the same det.rs trace format when comparing tick hashes. Run the regression controls
with `python3 living/tools/det_compare_selftest.py -v`.
See https://spacetimedb.com/docs/tables/auto-increment/ for which inserts use a sequence.
"""
import argparse
import hashlib
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


def det_wakes(log):
    """Each `det wakes tick=N due=[…] start=k` line (common::due_bystander_wakes, docs/COMBAT_PHASE.md
    "Wake order"): {N: (the due ids in id order, the start of the delivery)}."""
    out = {}
    for line in log.splitlines():
        try:
            msg = json.loads(line).get("message", "")
        except ValueError:
            continue
        m = re.match(r"det wakes tick=(\d+) due=\[([0-9, ]*)\] start=(\d+)$", msg)
        if m:
            out[int(m.group(1))] = (tuple(int(x) for x in m.group(2).split(",") if x.strip()), int(m.group(3)))
    return out


def wakes_compared(wa, wb, first_differ, rng):
    """The due bystander wakes of both builds, tick by tick, up to the first tick whose hashes differ
    (after it the worlds differ, and so may what is due): the ticks with wakes due, those whose due
    sets are the same, those delivered in the same order, and those the candidate reordered."""
    upto = [t for t in rng if first_differ is None or t <= first_differ]
    both = [t for t in upto if t in wa or t in wb]
    def order(w):
        due, k = w
        return due[k:] + due[:k]
    same_set = [t for t in both if t in wa and t in wb and wa[t][0] == wb[t][0]]
    same_order = [t for t in same_set if order(wa[t]) == order(wb[t])]
    rotated = [t for t in rng if t in wb and len(wb[t][0]) > 1 and wb[t][1] != 0]
    due_n = [len(w[0]) for w in wb.values()]
    return {
        "upto_tick": first_differ,
        "ticks_with_wakes": len(both),
        "same_set": len(same_set),
        "same_order": len(same_order),
        "set_differs": [t for t in both if t not in same_set][:20],
        "candidate_ticks_reordered": len(rotated),
        "first_reordered": rotated[:5],
        "candidate_due_per_tick": {"ticks": len(due_n), "mean": round(sum(due_n) / len(due_n), 2) if due_n else 0, "max": max(due_n, default=0)},
        "at_first_differ": {"base": wa.get(first_differ), "candidate": wb.get(first_differ)} if first_differ else None,
    }


# Auto-increment tables: SpacetimeDB 2.14.1 skips a sequence ahead to its next block of 4,096 at
# random (seeded from the operating system at each database load), so the same rows get other ids
# on two servers. Rows are compared with each such id by its rank among its table's ids, and the
# references the battle writes renamed alike, as `det.rs` hashes them.
AUTO_INC = """acquaintance act_queue artifact audience belief bond_offer character chronicle combat_seen
community cue expecting experience familiar far_handle fight_seen ground_edit guest heard_asleep
inventory join_request judged judgment know_how known_ground law_change look_line membership missile
perceived place practice projected record_party record relation remembered reveal routine seen_stock
seen_structures sex_seen skill_use structure thought trade_offer resource_node""".split()
# Players' tables (det.rs): rows inserted in a hash set's order, which a module instance's history
# decides, so two copies give the same rows other ids. Compared by content, the id columns left out
# (and the ids naming them: the mirror's `projected` id, act outcomes' and released lines'
# `experience` id).
CONTENT = ("perceived", "projected", "seen_character_copy", "act_outcome", "line_seen")
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
        x = re.sub(r"#(\d{10})(?!\d)", lambda m: "#%010d" % far(int(m.group(1))) if FAR_BASE <= int(m.group(1)) < 2**32 else m.group(0), x)
        # A far handle in a scene's JSON (a deliberation's `"id":1000008249`), renamed alike.
        return re.sub(r'"id":(\d{10})(?!\d)', lambda m: '"id":%010d' % far(int(m.group(1))) if FAR_BASE <= int(m.group(1)) < 2**32 else m.group(0), x)

    def target_rank(n):
        if FAR_BASE <= n < 2**32 and "far_handle" in ids:
            return f"far_handle:{rank('far_handle', n - FAR_BASE)}"
        for table in ("character", "structure", "resource_node"):
            if table in ids:
                k = rank(table, n)
                if k < STRUCTURE_BIT:
                    return f"{table}:{k}"
        return str(n)

    def rank_field(row, key, table):
        if isinstance(row, dict) and type(row.get(key)) is int and table in ids:
            row[key] = rank(table, row[key])

    def scene(source):
        try:
            value = json.loads(source)
        except (ValueError, TypeError):
            return source
        if not isinstance(value, dict):
            return source
        you = value.get("you", {})
        rank_field(you, "id", "character")
        for key in ("creatures", "you smell (out of sight)"):
            for row in value.get(key, []):
                n = row.get("id")
                if type(n) is int and FAR_BASE <= n < 2**32:
                    row["id"] = far(n)
                else:
                    rank_field(row, "id", "character")
                rank_field(row.get("visibly"), "at", "character")
        for row in value.get("structures", []):
            rank_field(row, "id", "structure")
        for row in value.get("resources", []):
            rank_field(row.get("nearest"), "id", "resource_node")
        for key, party in (("asked of you", "from"), ("you are waiting on", "to")):
            for row in you.get(key, []):
                rank_field(row, party, "character")
                rank_field(row, "offer", "trade_offer")
        earshot = "who would hear you now"
        if earshot in value:
            def hearer(match):
                n = int(match[0])
                table, key = ("far_handle", n - FAR_BASE) if FAR_BASE <= n < 2**32 else ("character", n)
                return f"{table}:{rank(table, key)}" if table in ids else match[0]

            value[earshot] = re.sub(r"(?<=\(#)[0-9]+(?=\))", hearer, value[earshot])
        queue = "decided, not yet done"
        if queue in you:
            you[queue] = [re.sub(r"(?<= → #)[0-9]+\Z", lambda m: target_rank(int(m[0])), act)
                          for act in you[queue]]
        value = deep(value)
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    def reason(source):
        def rename(pattern, table, line):
            if table not in ids:
                return line
            return re.sub(pattern, lambda m: str(rank(table, int(m[0]))), line)

        lines = []
        for line in source.split("\n"):
            line = rename(r"(?<=\(offer )[0-9]+(?=\), or let it pass\.)", "trade_offer", line)
            line = rename(r"(?<=\(#)[0-9]+(?=\) asks to start a family with you;)", "character", line)
            if line.startswith(("You long for a child with ", "You long for another child with ")):
                line = rename(r"(?<=\(#)[0-9]+(?=\)\.)", "character", line)
            elif line.startswith("What you had decided did not work out: "):
                line = re.sub(r"(?<= → #)[0-9]+(?=:)|(?<=no #)[0-9]+(?= in sight)",
                              lambda m: target_rank(int(m[0])), line)
                line = rename(r"(?<=#)[0-9]+(?= is dead: their remains lie in sight)", "character", line)
            lines.append(line)
        return text("\n".join(lines))

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
            if t == "deliberation":
                r = dict(r)
                rank_field(r, "actor", "character")
                r["scene"] = scene(r["scene"])
                r["reason"] = reason(r["reason"])
            else:
                r = deep(dict(r))
            if t in CONTENT:
                r["id"] = 0
                # A released line's copy of its experience row comes as a product (a list in
                # column order: id, observer, controller, at_ms, kind, subject, object, ...).
                if t == "line_seen" and isinstance(r.get("line"), list) and len(r["line"]) > 6:
                    line = list(r["line"])
                    line[0], line[5], line[6] = 0, far(line[5]), far(line[6])
                    r["line"] = line
                elif t == "line_seen" and isinstance(r.get("line"), dict):
                    r["line"] = {**r["line"], "id": 0, "subject": far(r["line"].get("subject")), "object": far(r["line"].get("object"))}
            elif t in AUTO_INC:
                r["id"] = rank(t, r["id"])
            if t == "experience":
                r["subject"], r["object"] = far(r["subject"]), far(r["object"])
            elif t == "inventory":
                r["owner"] = skey(r["owner"], STRUCTURE_BIT)
            elif t == "resource_node" and r["pool"] != 0:
                rank_field(r, "pool", "resource_node")
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
    if a.remains:
        # A field of remains under the battle (growth-fix-2: what is noticed with many bodies in
        # sight): `--remains N` fighters spawned where the battle will be and killed at once,
        # each leaving remains with a dead owner, before the battle itself is staged.
        before = {r["id"] for r in A.sql(db, "SELECT id FROM character")}
        A.call(db, "spawn_battle", [a.remains])
        doomed = sorted(r["id"] for r in A.sql(db, "SELECT id FROM character") if r["id"] not in before)
        for cid in doomed:
            A.call(db, "kill", [cid, "fixture"])
        print(f"det_compare: {len(doomed)} remains staged under the battle", flush=True)
    # The battle staged by the base build: `spawn_battle`, or `--sides N` the sides fixture
    # (`spawn_battle_sides`, or with `--layout-seed` the fixed-layout one, sides-layout-seed).
    if a.sides and a.layout_seed is not None:
        A.call(db, "spawn_battle_sides_layout", [a.fighters, a.sides, a.layout_seed, a.deal])
    elif a.sides:
        A.call(db, "spawn_battle_sides", [a.fighters, a.sides])
    else:
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
    meta = {"db": db, "start_tick": t0, "stop_tick": t0 + a.ticks, "fighters": a.fighters, "sides": a.sides,
            "layout": {"seed": a.layout_seed, "deal": a.deal} if a.sides and a.layout_seed is not None else None, "players": a.players, "remains": a.remains, "ring": a.ring, "ticks": a.ticks, "replica": A.newest_replica(), "made_with": a.base}
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
    # Whether the copies were pinned to cores (`--cpus ""`: unpinned, as on a host whose rootless
    # cgroups have no cpuset controller); the hashes do not depend on it, the run time does.
    res = {**meta, "base": a.base, "candidate": a.candidate, "pinned": bool(a.cpus), "cpus": a.cpus or None}
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
        if a.scripts:
            # Each build's own shipped script on its copy (the `just living-publish` path).
            import install_script
            srcs = a.scripts.split(",")
            assert len(srcs) == 2, "--scripts BASE.rhai,CAND.rhai"
            res["scripts"], res["scripts_seed"] = srcs, a.seed
            for s, src in zip(servers, srcs):
                source, _ = install_script.seed_script(a.seed, Path(src).read_text())
                code, body = s.http(f"/v1/database/{db}/call/install_script", [source])
                if code != 200:
                    raise RuntimeError(f"install_script on {s.c}: {code} {body[-500:]}")
                made = s.sql(db, "SELECT source FROM script WHERE name = 'skills'")[0]["source"]
                assert install_script.same_script(made, source), f"{s.c}: the installed script is not the one sent"
                res.setdefault("scripts_sha256", []).append(hashlib.sha256(install_script.without_world_laws(made).encode()).hexdigest())
                print(f"det_compare: {s.c} runs {src} ({len(source)} bytes{', seed ' + a.seed + ' laws composed' if a.seed else ''})", flush=True)
        for law in a.candidate_law:
            # A negative control: a law set on the candidate copy alone.
            name, value = law.split("=", 1)
            Y.call(db, "set_world_law", [name, value])
        res["candidate_laws"] = a.candidate_law
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
        log_a, log_b = X.replica_log(replica), Y.replica_log(replica)
        la, lb = det_ticks(log_a), det_ticks(log_b)
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
        res["wakes"] = wakes_compared(det_wakes(log_a), det_wakes(log_b), differ[0]["tick"] if differ else None, rng)
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
    ap.add_argument("--sides", type=int, default=0, help="prepare: the fighters in this many sides (spawn_battle_sides) instead of spawn_battle")
    ap.add_argument("--layout-seed", type=int, default=None, help="prepare: with --sides, the fixed layout (spawn_battle_sides_layout)")
    ap.add_argument("--deal", type=int, default=0, help="prepare: with --layout-seed, the place deal (1: the sides swapped)")
    ap.add_argument("--remains", type=int, default=0, help="prepare: this many fighters spawned and killed first, a field of remains under the battle")
    ap.add_argument("--players", type=int, default=0, help="prepare: players joined (no connection) and placed on --ring round the battle (exact items)")
    ap.add_argument("--ring", default="10,10", help="prepare: the players' ring LO,HI m from the battle's centre")
    ap.add_argument("--ports", default=None, help="run: the two copies' ports, PX,PY")
    ap.add_argument("--out")
    ap.add_argument("--keep-copies", action="store_true")
    ap.add_argument("--tag", default="", help="run: a suffix for the copies' names (two runs at once)")
    ap.add_argument("--stop", type=int, default=0, help="run: pause both copies at this tick instead of the template's det_stop")
    ap.add_argument("--candidate-law", action="append", default=[], metavar="NAME=VALUE", help="run: a world law set on the candidate copy alone before unpausing (a negative control)")
    ap.add_argument("--scripts", help="run: BASE.rhai,CAND.rhai, each build's shipped script, installed on its copy before unpausing")
    ap.add_argument("--seed", default=None, help="run: with --scripts, the seed whose laws are composed over each script (e.g. cullet)")
    ap.add_argument("--cpus", default="0-4,10-14", help="run: the copies' cores (default the Spark's A725 cores, away from pinned measurements)")
    a = ap.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    return {"prepare": prepare, "run": run, "delete": delete}[a.step](a)


if __name__ == "__main__":
    sys.exit(main())
