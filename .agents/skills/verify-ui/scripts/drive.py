#!/usr/bin/env python3
"""Drive the real game client headless on a verify-ui scratch world, through the live script.

  drive.py --run RUN --name NAME --plan 'ready;dump:a;click:@menu:Settings;shot:b;quit'
           [--place ID:DX:DY ...] [--sync NAME='REDUCER|ARG|..;...'] [--size 1600x900]
           [--client PATH] [--expect 'regex' ...]

- RUN is the verify run (`verify.py launch --run RUN --seed island`); the world is
  `verify-RUN`, which must start with `verify-ui-`.
- The client is the release build from this checkout's CARGO_TARGET_DIR (default
  `.local/target/release/living-game`), or --client. It joins as "Verifier" with its own token
  under the evidence directory, and its settings file (bindings, Play settings) is a scratch
  file there too (LIVING_GAME_SETTINGS), so a run never touches the owner's.
- Evidence: `.local/living/verify/RUN/ui/NAME/` holds the photographs and dumps the plan writes
  (`shot:`, `dump:`), `client.log`, `plan.txt` and `scene.json` (the player's id, the admin calls
  made at `sync:` steps and their replies).
- `--place ID:DX:DY` puts character ID at DX, DY metres from the player and holds it still
  (`{"wait": 600}`) when the plan reaches `sync:scene`. `--sync NAME=...` makes admin calls when
  the plan reaches `sync:NAME`; `{me}` is the player's id and `(expr)` a Python expression of
  mx, my (the player's position) and me. Admin calls set scenes only; they are not player acts.
- `--expect REGEX` (repeatable) must match client.log, else the run fails (exit 1).

Exit code: the client's, or 1 when an expectation fails or the client never joined.
"""
import argparse, json, os, re, subprocess, sys, time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))
STDB = os.path.join(ROOT, "living/tools/stdb")


def stdb(*args):
    r = subprocess.run([STDB] + [str(a) for a in args], capture_output=True, text=True)
    out = (r.stdout + r.stderr).replace("WARNING: This command is UNSTABLE and subject to breaking changes.", "").strip()
    return r.returncode, out


def call(db, reducer, *args):
    code, out = stdb("call", "-s", "local", db, reducer, *args)
    return {"reducer": reducer, "args": [str(a) for a in args], "code": code, "out": out[-400:]}


def body(db, cid):
    _, out = stdb("sql", "-s", "local", db, f"SELECT x, y FROM body WHERE id = {cid}")
    m = re.findall(r"^\s*([-\d.]+)\s*\|\s*([-\d.]+)\s*$", out, re.M)
    return (float(m[0][0]), float(m[0][1])) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--place", action="append", default=[])
    ap.add_argument("--sync", action="append", default=[])
    ap.add_argument("--size", default="1600x900")
    ap.add_argument("--client")
    ap.add_argument("--player", default="Verifier")
    ap.add_argument("--expect", action="append", default=[])
    ap.add_argument("--timeout", type=float, default=600)
    a = ap.parse_args()
    db = f"verify-{a.run}"
    if not db.startswith("verify-ui-"):
        sys.exit(f"refusing {db}: verify-ui runs use verify-ui-* worlds (run names ui-*)")
    out = os.path.join(ROOT, ".local/living/verify", a.run, "ui", a.name)
    os.makedirs(out, exist_ok=True)
    for f in os.listdir(out):
        if f.endswith(".go"):
            os.remove(os.path.join(out, f))
    client = a.client or os.path.join(os.environ.get("CARGO_TARGET_DIR", os.path.join(ROOT, ".local/target")), "release/living-game")
    if not os.path.exists(client):
        sys.exit(f"no client at {client}: build it with cargo build --release -p living-game")
    places = [tuple(p.split(":")) for p in a.place]
    syncs = {}
    for s in a.sync:
        name, calls = s.split("=", 1)
        syncs[name] = [c.split("|") for c in calls.split(";") if c]
    open(os.path.join(out, "plan.txt"), "w").write(a.plan.replace(";", ";\n") + "\n")
    token = os.path.join(ROOT, ".local/living/verify", a.run, "ui", "player.token")
    # A worker's own server (`LIVING_STDB_URL`, the verify entry point's "Your own server"), else the shared one.
    env = dict(os.environ, LIVING_SERVER=os.environ.get("LIVING_STDB_URL", "http://127.0.0.1:3300"), LIVING_DB=db, LIVING_GAME_NAME=a.player, LIVING_GAME_TOKEN=token,
               LIVING_GAME_LIVE=out, LIVING_GAME_LIVE_PLAN=a.plan, LIVING_GAME_SIZE=a.size,
               LIVING_GAME_SETTINGS=os.path.join(out, "settings.json"), RUST_LOG=os.environ.get("RUST_LOG", "info,wgpu=warn,naga=warn"))
    log_path = os.path.join(out, "client.log")
    log = open(log_path, "w")
    p = subprocess.Popen([client], env=env, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)
    print(f"client pid {p.pid}; evidence {out}", flush=True)
    scene = {"world": db, "plan": a.plan, "places": places, "calls": [], "client": client}
    me, placed, t0 = None, False, time.time()
    while p.poll() is None:
        if time.time() - t0 > a.timeout:
            print(f"timeout after {a.timeout} s: stopping the client (pid {p.pid})", flush=True)
            p.terminate()
            break
        text = open(log_path, errors="replace").read()
        if me is None:
            m = re.search(r"playing character #(\d+)", text)
            if m:
                me = int(m.group(1))
                scene["me"] = me
        if me is not None and not placed and "scene.go" in text and "waiting for" in text:
            at = body(db, me)
            scene["me_at"] = at
            for i, dx, dy in places:
                scene["calls"].append(call(db, "place_at", i, at[0] + float(dx), at[1] + float(dy)))
                scene["calls"].append(call(db, "set_behavior", i, json.dumps(json.dumps({"wait": 600}))))
            time.sleep(1.0)
            # Where each landed: `place_at` snaps to the nearest walkable tile, so two asked-for
            # spots in a stall can share one.
            scene["placed"] = {i: body(db, int(i)) for i, _, _ in places}
            open(os.path.join(out, "scene.go"), "w").close()
            placed = True
        for name, calls in list(syncs.items()):
            if me is not None and f"{name}.go" in text and "waiting for" in text:
                at = body(db, me)
                sub = lambda s: str(eval(s[1:-1], {"mx": at[0], "my": at[1], "me": me})) if s.startswith("(") else s.replace("{me}", str(me))
                for c in calls:
                    scene["calls"].append(call(db, c[0], *[sub(x) for x in c[1:]]))
                time.sleep(0.5)
                moved = sorted({sub(c[1]) for c in calls if c[0] == "place_at"})
                if moved:
                    scene.setdefault("placed_at", {})[name] = {i: body(db, int(i)) for i in moved}
                open(os.path.join(out, f"{name}.go"), "w").close()
                del syncs[name]
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
