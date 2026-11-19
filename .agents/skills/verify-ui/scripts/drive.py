#!/usr/bin/env python3
"""Drive the real game client headless on a verify-ui scratch world, through the live script.

  drive.py --run RUN --name NAME --plan 'ready;dump:a;click:@menu:Settings;shot:b;quit'
           [--place ID:DX:DY ...] [--sync NAME='REDUCER|ARG|..;...'] [--size 1600x900]
           [--client PATH] [--player NAME] [--token FILE] [--expect 'regex' ...]

- RUN is the verify run (`verify.py launch --run RUN --seed island`); the world is
  `verify-RUN`, which must start with `verify-ui-`.
- The client is the release build from this checkout's CARGO_TARGET_DIR (default
  `.local/target/release/living-game`), or --client. It joins as "Verifier" with its own token
  under the evidence directory (`--token FILE` plays another character, e.g. verify.py's player
  identity: the token string in a file), and its settings file (bindings, Play settings) is a scratch
  file there too (LIVING_GAME_SETTINGS), so a run never touches the owner's.
- Evidence: `.local/living/verify/RUN/ui/NAME/` holds the photographs and dumps the plan writes
  (`shot:`, `dump:`), `client.log`, `plan.txt` and `scene.json` (the player's id, the admin calls
  made at `sync:` steps and their replies).
- `--place ID:DX:DY` puts character ID at DX, DY metres from the player and holds it still
  (`{"wait": 600}`) when the plan reaches `sync:scene`. `--sync NAME=...` makes admin calls when
  the plan reaches `sync:NAME`; `{me}` is the player's id and `(expr)` a Python expression of
  mx, my (the player's position) and me. Admin calls set scenes only; they are not player acts.
- A `--sync` call `sql|QUERY` instead snapshots the authority (owner SQL through verify.py) at
  that moment: the rows and the wall time go into scene.json under "snaps" by NAME. `{me}` is
  the player's character id, `{ident}` its identity (hex), and `{epoch_at:HOUR}` the world
  epoch that makes the world's hour HOUR now, keeping its day count (for a scratch fixture
  `UPDATE world SET epoch_ms = {epoch_at:12} WHERE id = 0`: the hour by day or night).
- `client_sql|QUERY` snapshots a view as the game client identity.
- A `--sync` call `player|REDUCER|ARG|…` is made as verify.py's player identity (`$V player
  join`), not the admin: a second player's own acts (`player|human_face|0|-1`), beside mine.
- `--admin-link` gives the client the world admin's token in a private file
  (LIVING_GAME_ADMIN_TOKEN_FILE, `.local/living/verify/RUN/private/`, mode 600, deleted when the
  drive ends), as the play launcher does for a scene with `"law_toggle": true`: the client's
  second, admin-only connection switches facing sight (`set_world_law("fov_on", …)`, F5).
- `--place-free ID:DX:DY` puts a resident near that offset on a free walkable tile 1.5-3 m from
  the player with nothing opaque between (chosen from the terrain and the bodies, so where it
  lands is known: `scene.json` `free_spots`); `--sync NAME=refree` puts them back there.
- `--expect REGEX` (repeatable) must match client.log, else the run fails (exit 1).

Exit code: the client's, or 1 when an expectation fails or the client never joined.
"""
import argparse, signal, json, os, re, subprocess, sys, time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))
STDB = os.path.join(ROOT, "living/tools/stdb")
V = os.path.join(ROOT, ".agents/skills/verify/scripts/verify.py")
sys.path.insert(0, os.path.dirname(V))
from verify import admin_token, http, load, refresh_lease, require_running


def stdb(*args):
    r = subprocess.run([STDB] + [str(a) for a in args], capture_output=True, text=True)
    out = (r.stdout + r.stderr).replace("WARNING: This command is UNSTABLE and subject to breaking changes.", "").strip()
    return r.returncode, out


def call(db, reducer, *args):
    code, out = stdb("call", "-s", "local", db, reducer, *args)
    return {"reducer": reducer, "args": [str(a) for a in args], "code": code, "out": out[-400:]}


def sql(run, q, *, required=False):
    r = subprocess.run([sys.executable, V, "sql", "--run", run, q], capture_output=True, text=True)
    if required and r.returncode:
        sys.exit(r.stderr.strip() or f"owner SQL failed: {q}")
    i = r.stdout.find("[")
    try:
        return json.loads(r.stdout[i:]) if i >= 0 else []
    except ValueError:
        return []


def epoch_at(run, hour):
    """The world epoch (ms) under which `living_rules::hour_of` gives `hour` now, keeping the
    world's day count (the world starts at 07:00)."""
    w = sql(run, "SELECT epoch_ms, day_ms FROM world")[0]
    day, now = int(w["day_ms"]), int(time.time() * 1000)
    days = (now - int(w["epoch_ms"]) + day * 7 // 24) // day
    return now + day * 7 // 24 - int(hour / 24.0 * day) - days * day


WALK_BLOCKED = {2, 4, 7, 8, 9}  # water, rock, wall, drop, low (`Terrain::walkable`)
OPAQUE = {4, 7}  # rock, wall


def vsql(run, q):
    """Owner SQL through verify.py, as JSON rows."""
    r = subprocess.run([sys.executable, os.path.join(ROOT, ".agents/skills/verify/scripts/verify.py"), "sql", "--run", run, q], capture_output=True, text=True)
    i = r.stdout.find("[")
    return json.loads(r.stdout[i:]) if i >= 0 else []


def free_tiles(run, me_at, wants, keep=(1.5, 3.0)):
    """A tile centre for each asked offset from me: walkable, no body on it, keep[0]..keep[1] m
    from me with no rock or wall between, apart from the others chosen, nearest the asked point
    (`place_at` since fix-place-free takes the nearest free tile; this picks it first, so where
    each lands is known)."""
    import math
    xs, ys = (me_at[0] - 6, me_at[0] + 6), (me_at[1] - 6, me_at[1] + 6)
    t = {}
    for cy in range(int(ys[0]) // 16, int(ys[1]) // 16 + 1):
        for cx in range(int(xs[0]) // 16, int(xs[1]) // 16 + 1):
            row = vsql(run, f"SELECT tiles FROM terrain_chunk WHERE id = {(cy << 16) | cx}")
            if row:
                b = row[0]["tiles"]
                b = bytes.fromhex(b) if isinstance(b, str) else bytes(b)
                for k, v in enumerate(b):
                    t[(cx * 16 + k % 16, cy * 16 + k // 16)] = v
    taken = {(math.floor(r["x"]), math.floor(r["y"])) for r in vsql(run, "SELECT id, x, y FROM body")}
    def clear(c):
        n = int(math.dist(me_at, c) * 4) + 1
        return all(t.get((math.floor(me_at[0] + (c[0] - me_at[0]) * i / n), math.floor(me_at[1] + (c[1] - me_at[1]) * i / n))) not in OPAQUE for i in range(n + 1))
    out = []
    for dx, dy in wants:
        want = (me_at[0] + dx, me_at[1] + dy)
        cands = [(tx + .5, ty + .5) for tx in range(int(xs[0]), int(xs[1]) + 1) for ty in range(int(ys[0]), int(ys[1]) + 1)]
        cands = [c for c in cands if keep[0] <= math.dist(c, me_at) <= keep[1] and t.get((math.floor(c[0]), math.floor(c[1])), 4) not in WALK_BLOCKED
                 and (math.floor(c[0]), math.floor(c[1])) not in taken and all(math.dist(c, o) >= 1.5 for o in out) and clear(c)]
        out.append(min(cands, key=lambda c: math.dist(c, want)) if cands else want)
    return out


def body(db, cid):
    _, out = stdb("sql", "-s", "local", db, f"SELECT x, y FROM body WHERE id = {cid}")
    m = re.findall(r"^\s*([-\d.]+)\s*\|\s*([-\d.]+)\s*$", out, re.M)
    return (float(m[0][0]), float(m[0][1])) if m else None


SYNC_WAIT = re.compile(r"^\S+\s+INFO\s+living_game::live: live script: waiting for (.+)$")


def next_sync_wait(text, offset, pending):
    """Return the next pending sync name and the cursor after its complete log line."""
    while (end := text.find("\n", offset)) != -1:
        line = text[offset:end]
        offset = end + 1
        match = SYNC_WAIT.fullmatch(re.sub(r"\x1b\[[0-9;]*m", "", line))
        if match and match[1] in pending:
            return pending[match[1]], offset
    return None, offset


def self_test():
    prefix = "2026-11-19T16:12:04.498308Z  INFO living_game::live: live script: waiting for "
    out = "/tmp/verify ui"
    pending = {f"{out}/{name}.go": name for name in ("up", "sit", "setup", "scene")}
    text = f"{prefix}{out}/not-scene.go\nother: waiting for\nother: {out}/scene.go\n"
    text += f"{prefix}/other/scene.go\n{prefix}{out}/up.go.old\n"
    name, offset = next_sync_wait(text, 0, pending)
    assert name is None
    for expected in ("setup", "scene", "sit", "up"):
        text += f"{prefix}{out}/{expected}.go"
        name, offset = next_sync_wait(text, offset, pending)
        assert name is None, name  # A poll may catch a partially written line.
        text += "\n"
        name, offset = next_sync_wait(text, offset, pending)
        assert name == expected, (name, expected)
        name, offset = next_sync_wait(text, offset, pending)
        assert name is None, name  # Even a still-pending name cannot reuse an old wait.
    print("PASS: exact, ordered, single-use sync waits")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true", help="check sync matching offline")
    ap.add_argument("--run")
    ap.add_argument("--name")
    ap.add_argument("--plan")
    ap.add_argument("--place", action="append", default=[])
    ap.add_argument("--place-free", action="append", default=[], help="ID:DX:DY near that offset, on a free walkable tile in sight 1.5-3 m from me")
    ap.add_argument("--sync", action="append", default=[])
    ap.add_argument("--size", default="1600x900")
    ap.add_argument("--client")
    ap.add_argument("--player", default="Verifier")
    ap.add_argument("--token", help="another player's token file (default: the run's ui/player.token)")
    ap.add_argument("--expect", action="append", default=[])
    ap.add_argument("--admin-link", action="store_true")
    ap.add_argument("--timeout", type=float, default=600)
    a = ap.parse_args()
    if a.self_test:
        self_test()
        return
    if any(value is None for value in (a.run, a.name, a.plan)):
        ap.error("--run, --name and --plan are required for a client drive")
    db = f"verify-{a.run}"
    if not db.startswith("verify-ui-"):
        sys.exit(f"refusing {db}: verify-ui runs use verify-ui-* worlds (run names ui-*)")
    st = load(a.run)
    owner = admin_token()
    require_running(st, owner)
    out = os.path.join(ROOT, ".local/living/verify", a.run, "ui", a.name)
    os.makedirs(out, exist_ok=True)
    for f in os.listdir(out):
        if f.endswith(".go"):
            os.remove(os.path.join(out, f))
    client = a.client or os.path.join(os.environ.get("CARGO_TARGET_DIR", os.path.join(ROOT, ".local/target")), "release/living-game")
    if not os.path.exists(client):
        sys.exit(f"no client at {client}: build it with cargo build --release -p living-game")
    places = [tuple(p.split(":")) for p in a.place]
    free_places = [tuple(p.split(":")) for p in a.place_free]
    syncs = {}
    for s in a.sync:
        name, calls = s.split("=", 1)
        syncs[name] = [c.split("|") for c in calls.split(";") if c]
    open(os.path.join(out, "plan.txt"), "w").write(a.plan.replace(";", ";\n") + "\n")
    token = a.token or os.path.join(ROOT, ".local/living/verify", a.run, "ui", "player.token")
    # A worker's own server (`LIVING_STDB_URL`, the verify entry point's "Your own server"), else the shared one.
    env = dict(os.environ, LIVING_SERVER=os.environ.get("LIVING_STDB_URL", "http://127.0.0.1:3300"), LIVING_DB=db, LIVING_GAME_NAME=a.player, LIVING_GAME_TOKEN=token,
               LIVING_GAME_LIVE=out, LIVING_GAME_LIVE_PLAN=a.plan, LIVING_GAME_SIZE=a.size,
               LIVING_GAME_SETTINGS=os.path.join(out, "settings.json"), RUST_LOG=os.environ.get("RUST_LOG", "info,wgpu=warn,naga=warn"))
    secret = None
    if a.admin_link:
        d = os.path.join(ROOT, ".local/living/verify", a.run, "private")
        os.makedirs(d, mode=0o700, exist_ok=True)
        os.chmod(d, 0o700)
        secret = os.path.join(d, f"admin-{os.getpid()}.token")
        if os.path.exists(secret):
            os.remove(secret)
        fd = os.open(secret, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(owner)
        env["LIVING_GAME_ADMIN_TOKEN_FILE"] = secret
    try:
        run_client(a, db, out, client, env, places, syncs, free_places, st, owner)
    finally:
        if secret and os.path.exists(secret):
            os.remove(secret)
            print("admin token file deleted", flush=True)


def run_client(a, db, out, client, env, places, syncs, free_places, st, owner):
    log_path = os.path.join(out, "client.log")
    log = open(log_path, "w")
    p = subprocess.Popen([client], env=env, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)
    print(f"client pid {p.pid}; evidence {out}", flush=True)
    # Whatever ends this drive (a scene's error, a SIGTERM or SIGHUP from whoever ran it), the
    # client goes with it, by its own pid (`stop`); a SIGKILL cannot be caught, and the client
    # then quits by itself once its parent is gone (live.rs, `parent_pid`).
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda n, _f: sys.exit(128 + n))
    try:
        return drive_client(a, db, out, client, p, log_path, places, syncs, env["LIVING_GAME_TOKEN"], free_places, st, owner)
    finally:
        stop(p)


def stop(p):
    """End the client this drive started, by its pid: a terminate, then a kill after 10 s."""
    if p.poll() is not None:
        return
    print(f"stopping the client (pid {p.pid})", flush=True)
    p.terminate()
    try:
        p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()


def drive_client(a, db, out, client, p, log_path, places, syncs, token_path, free_places, st, owner):
    scene = {"world": db, "plan": a.plan, "places": places, "calls": [], "snaps": {}, "client": client, "admin_link": a.admin_link}
    me, t0, ident, last_at = None, time.time(), None, None
    pending = {os.path.join(out, f"{name}.go"): name for name in (*syncs, "scene")}
    offset = 0
    next_renewal = 0

    def act(reducer, *args):
        refresh_lease(st)
        return call(db, reducer, *args)

    def position(cid):
        refresh_lease(st)
        return body(db, cid)

    while p.poll() is None:
        if time.time() - t0 > a.timeout:
            print(f"timeout after {a.timeout} s: stopping the client (pid {p.pid})", flush=True)
            p.terminate()
            break
        # The connected client can spend minutes driving input between Python scene actions.
        if time.monotonic() >= next_renewal:
            refresh_lease(st)
            next_renewal = time.monotonic() + 1
        text = open(log_path, errors="replace").read()
        if me is None:
            m = re.search(r"playing character #(\d+)", text)
            if m:
                me = int(m.group(1))
                scene["me"] = me
        if me is None:
            time.sleep(0.4)
            continue
        name, offset = next_sync_wait(text, offset, pending)
        if name == "scene":
            at = position(me)
            scene["me_at"] = at
            for i, dx, dy in places:
                scene["calls"].append(act("place_at", i, at[0] + float(dx), at[1] + float(dy)))
                scene["calls"].append(act("set_behavior", i, json.dumps(json.dumps({"wait": 600}))))
            if free_places:
                spots = free_tiles(a.run, at, [(float(dx), float(dy)) for _, dx, dy in free_places])
                scene["free_spots"] = {i: list(c) for (i, _, _), c in zip(free_places, spots)}
                for (i, _, _), c in zip(free_places, spots):
                    scene["calls"].append(act("place_at", i, c[0], c[1]))
                    scene["calls"].append(act("set_behavior", i, json.dumps(json.dumps({"wait": 600}))))
                places = places + free_places
            require_running(st, owner)
            # Where each landed: `place_at` snaps to the nearest walkable tile, so two asked-for
            # spots in a stall can share one.
            scene["placed"] = {i: position(int(i)) for i, _, _ in places}
        if name in syncs:
            calls = syncs[name]
            # The player's position now, else where it last was (a body gone at death).
            at = position(me) or last_at
            last_at = at
            # `refree`: put the free-placed residents back on their own tiles (town life may
            # have walked them off).
            if calls == [["refree"]]:
                calls = [c for i, xy in scene.get("free_spots", {}).items() for c in (["place_at", i, str(xy[0]), str(xy[1])], ["set_behavior", i, json.dumps(json.dumps({"wait": 600}))])]
            sub = lambda s: str(eval(s[1:-1], {"mx": at[0], "my": at[1], "me": me})) if s.startswith("(") else s.replace("{me}", str(me))
            for c in calls:
                if c[0] in ("sql", "client_sql"):
                    if ident is None:
                        rows = sql(a.run, f"SELECT controller FROM character WHERE id = {me}")
                        ident = rows[0]["controller"] if rows else ""
                        ident = str(ident[0] if isinstance(ident, list) and ident else ident)
                        ident = ident[2:] if ident.startswith("0x") else ident
                    q = "|".join(c[1:]).replace("{me}", str(me)).replace("{ident}", ident)
                    for m in re.finditer(r"\{epoch_at:([\d.]+)\}", q):
                        q = q.replace(m.group(0), str(epoch_at(a.run, float(m.group(1)))))
                    wall_ms = int(time.time() * 1000)
                    if c[0] == "client_sql":
                        refresh_lease(st)
                        with open(token_path) as token_file:
                            status, response = http(f"/v1/database/{db}/sql", q, token_file.read().strip(), raw=True)
                        if status != 200:
                            sys.exit(f"client SQL {q}: {status} {response}")
                        result = json.loads(response)[-1]
                        names = [column["name"]["some"] for column in result["schema"]["elements"]]
                        rows = [dict(zip(names, row)) for row in result["rows"]]
                    else:
                        rows = sql(a.run, q, required=True)
                    scene["snaps"].setdefault(name, []).append({"query": q, "wall_ms": wall_ms, "rows": rows})
                    continue
                if c[0] == "player":
                    # As verify.py's player identity (`$V player join`), not the admin: its
                    # own reducers (human_move, human_face), a second player beside mine.
                    def val(x):
                        x = sub(x)
                        if x in ("true", "false"):
                            return x == "true"
                        # An id stays a whole number (a u32 argument takes no 311.0).
                        for kind in (int, float):
                            try:
                                return kind(x)
                            except ValueError:
                                pass
                        return x
                    args = json.dumps([val(x) for x in c[2:]])
                    r = subprocess.run([sys.executable, V, "call", "--run", a.run, c[1], args, "--as-player"], capture_output=True, text=True)
                    scene["calls"].append({"reducer": c[1], "as": "player", "args": args, "code": r.returncode, "out": (r.stdout + r.stderr)[-300:]})
                    continue
                scene["calls"].append(act(c[0], *[sub(x) for x in c[1:]]))
            time.sleep(0.5)
            moved = sorted({sub(c[1]) for c in calls if c[0] == "place_at"})
            if moved:
                scene.setdefault("placed_at", {})[name] = {i: position(int(i)) for i in moved}
        if name is not None:
            path = os.path.join(out, f"{name}.go")
            del pending[path]
            open(path, "w").close()
        time.sleep(0.4)
    p.wait()
    scene["exit"] = p.returncode
    json.dump(scene, open(os.path.join(out, "scene.json"), "w"), indent=1)
    text = open(log_path, errors="replace").read()
    failed = [e for e in a.expect if not re.search(e, text)]
    for e in failed:
        print(f"EXPECT FAILED: /{e}/ not in client.log", flush=True)
    for e in a.expect:
        if e not in failed:
            print(f"expect ok: /{e}/", flush=True)
    print(f"client exit {p.returncode}; me #{me}", flush=True)
    sys.exit(1 if failed or me is None else p.returncode)


if __name__ == "__main__":
    main()
