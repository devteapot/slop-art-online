#!/usr/bin/env python3
"""Labelled stills of a 200-fighter battle for the owner's battle-scale decision (branch
`battle-stills`, never merged; docs/BATTLE_LAWS.md option (a), `far_cap`).

  battle_stills.py --run RUN [--fighters 200] [--edge 9] [--out DIR] [--arms real,mock]

RUN is a verify-ui Cullet world (`verify.py launch --run RUN --seed cullet`). The harness:

- stages the battle with the admin's `spawn_battle` (dev-box's fixture: AI fighters within 7 m of
  the arrival less 20 m on a fight graph; no minds, no model);
- keeps it alive: every 0.4 s everyone hurt is set back to full health
  (`admin_set_vitals`, the agreed keep-alive fixture, extended to the fighters and to the
  residents and animals they attack), and a fighter
  that died anyway is replaced (`spawn_battle`) so the battle stays at `--fighters`;
- writes the crowd mock's feed (developer truth: owner SQL of every fighter's body, posed now,
  twice a second) to `<evidence>/crowd-feed.json`;
- drives the game client (drive.py) with the player placed `--edge` m south of the battle's centre,
  its cursor on the centre (facing into it), and for each arm sets `far_cap` with
  `set_world_law` (no republish), then takes a still at Far (19 m) and Middle (12 m) after the
  view has settled; the `mock` drive runs the client with LIVING_GAME_DEV_CROWD_MOCK on the feed;
- restores `far_cap` from the world's own laws (`own_laws`) at the end.

Per still it records the creatures the client perceives (the dump's `perceived`, less me; of them
the fighters), the characters drawn (`extra.lod`), the fighters alive in the battle and the
client's frame time (LIVING_GAME_FRAMES, uncapped) over the settled window.
"""
import argparse, concurrent.futures, json, math, os, re, sys, threading, time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import check  # noqa: E402  (drive, dump, log, sql helpers)
from check import ROOT, verify  # noqa: E402
sys.path.insert(0, os.path.join(ROOT, "living/tools"))
from law_values import own_laws  # noqa: E402
from verify_steering import pose  # noqa: E402

ARMS = {"real": [("off", "0"), ("40", "40"), ("25", "25")], "mock": [("40", "40"), ("25", "25")]}


class Battle:
    def __init__(self, run, fighters, feed):
        self.run, self.n, self.feed = run, fighters, feed
        self.st = verify.load(run)
        self.db = self.st["db"]
        self.token = verify.admin_token()
        self.ids = set()
        self.others = self.alive_ids()  # everyone alive before the battle (residents, animals)
        self.others_died = 0
        self.stop = threading.Event()
        self.timeline = []  # (wall_ms, alive fighters)
        self.calls = self.failed = self.respawned = self.deaths = 0
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=8)

    def sql(self, q):
        code, body = verify.http(f"/v1/database/{self.db}/sql", q, self.token, raw=True, timeout=30)
        if code != 200:
            raise RuntimeError(f"sql {q!r}: {code} {body[:200]}")
        res = json.loads(body)[0]
        names = [e["name"]["some"] if isinstance(e["name"], dict) else e["name"] for e in res["schema"]["elements"]]
        return [dict(zip(names, r)) for r in res["rows"]]

    def call(self, reducer, args):
        code, body = verify.http(f"/v1/database/{self.db}/call/{reducer}", args, self.token, timeout=30)
        if code != 200:
            raise RuntimeError(f"{reducer}{args}: {code} {body[:200]}")

    def alive_ids(self):
        return {r["id"] for r in self.sql("SELECT id, alive FROM character") if r["alive"]}

    def spawn(self, k):
        before = {r["id"] for r in self.sql("SELECT id FROM character")}
        self.call("spawn_battle", [k])
        new = {r["id"] for r in self.sql("SELECT id, name FROM character") if r["id"] not in before and r["name"].startswith("Fighter")}
        self.ids |= new
        return new

    def centre(self):
        at = time.time_ns() // 1_000_000
        rows = [r for r in self.sql("SELECT id, x, y, vx, vy, t_ms, next_ms, heading, turn, turn_s FROM body") if r["id"] in self.ids]
        pts = [pose(r, at) for r in rows]
        return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)) if pts else None

    def keep(self):
        while not self.stop.wait(0.4):
            try:
                verify.refresh_lease(self.st)
                alive = self.alive_ids()
                dead = {i for i in self.ids if i not in alive}
                if dead:
                    self.deaths += len(dead)
                    self.ids -= dead
                gone = {i for i in self.others if i not in alive}
                if gone:
                    self.others_died += len(gone)
                    self.others -= gone
                # Everyone alive is kept alive: the fighters, the player and the residents and
                # animals the fighters attack (a dead bystander leaves `remains` on the ground).
                hurt = [r for r in self.sql("SELECT id, hp, max_hp FROM vitals") if r["id"] in alive and r["hp"] < r["max_hp"]]

                def heal(r):
                    try:
                        self.call("admin_set_vitals", [r["id"], r["max_hp"]])
                        return 1
                    except RuntimeError:
                        return 0
                ok = sum(self.pool.map(heal, hurt))
                self.calls += ok
                self.failed += len(hurt) - ok
                short = self.n - len(self.ids)
                if short > 0:
                    self.respawned += len(self.spawn(short))
                self.timeline.append((time.time_ns() // 1_000_000, len(self.ids)))
            except Exception as e:  # keep going: a slow SQL under load is not fatal
                print(f"keeper: {e}", flush=True)

    def feed_loop(self):
        while not self.stop.wait(0.5):
            try:
                at = time.time_ns() // 1_000_000
                rows = [r for r in self.sql("SELECT id, x, y, vx, vy, t_ms, next_ms, heading, turn, turn_s FROM body") if r["id"] in self.ids]
                bodies = [{"id": r["id"], "x": round(p[0], 2), "y": round(p[1], 2), "side": 0} for r in rows for p in [pose(r, at)]]
                tmp = self.feed + ".tmp"
                with open(tmp, "w") as f:
                    json.dump({"wall_ms": at, "bodies": bodies}, f)
                os.replace(tmp, self.feed)
            except Exception as e:
                print(f"feed: {e}", flush=True)

    def alive_at(self, wall_ms):
        before = [n for t, n in self.timeline if t <= wall_ms]
        return before[-1] if before else None


def frames_between(path, lo_us, hi_us):
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path):
        try:
            unix, delta, _ = map(int, line.split(","))
        except ValueError:
            continue
        if lo_us < unix < hi_us:
            out.append(delta / 1000)
    return sorted(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True)
    ap.add_argument("--fighters", type=int, default=200)
    ap.add_argument("--edge", type=float, default=9.0, help="the player's distance south of the battle's centre (m)")
    ap.add_argument("--arms", default="real,mock")
    ap.add_argument("--settle", type=float, default=4.0)
    a = ap.parse_args()
    run = a.run
    assert run.startswith("ui-"), "a verify-ui run"
    ev = os.path.join(ROOT, ".local/living/verify", run, "ui")
    os.makedirs(ev, exist_ok=True)
    feed = os.path.join(ev, "crowd-feed.json")
    b = Battle(run, a.fighters, feed)
    own = own_laws(b.sql)
    original_cap = own.get("far_cap")
    print(f"world's own far_cap: {original_cap!r}", flush=True)
    b.spawn(a.fighters)
    print(f"battle: {len(b.ids)} fighters", flush=True)
    keeper = threading.Thread(target=b.keep, daemon=True)
    feeder = threading.Thread(target=b.feed_loop, daemon=True)
    keeper.start()
    feeder.start()
    time.sleep(3)
    cx, cy = b.centre()
    # North is -y: the player stands south of the centre and faces north into the battle.
    px, py = cx, cy + a.edge
    print(f"centre ({cx:.1f}, {cy:.1f}); player at ({px:.1f}, {py:.1f})", flush=True)
    results = {"run": run, "db": b.db, "fighters": a.fighters, "centre": [cx, cy], "player_at": [px, py], "edge_m": a.edge,
               "far_cap_own": original_cap, "stills": []}
    try:
        for kind in a.arms.split(","):
            arms = ARMS[kind]
            name = f"battle-stills-{kind}"
            frames = os.path.join(ev, f"{name}.frames.csv")
            syncs = ["noon=sql|UPDATE world SET epoch_ms = {epoch_at:12} WHERE id = 0",
                     f"place=place_at|{{me}}|{px:.2f}|{py:.2f}"]
            plan = ["ready", "wait:1", "click:@tip:ok", "wait:1", "sync:noon", "sync:place", "wait:2", f"pointat:{cx:.2f},{cy:.2f}:1.0", "wait:1"]
            for label, value in arms:
                syncs.append(f"cap_{label}=set_world_law|\"far_cap\"|\"{value}\"")
                plan += [f"sync:cap_{label}", "wait:5"]
                for stop, notches in (("far", -30), ("middle", 11)):
                    key = f"{label}_{stop}"
                    plan += [f"notches:{notches}", f"wait:{a.settle}", f"dump:{key}_a", "wait:3", f"dump:{key}", f"shot:{key}"]
            plan.append("quit")
            env = {"LIVING_GAME_FRAMES": frames, "LIVING_GAME_FPS_CAP": "0"}
            if kind == "mock":
                env["LIVING_GAME_DEV_CROWD_MOCK"] = feed
            out, code, msg = check.drive(run, name, ";".join(plan), syncs=syncs, env=env)
            print(f"{name}: exit {code}", flush=True)
            if code:
                print(msg[-1500:], flush=True)
            trace = check.log(out)
            times = {}
            for stamp, label in re.findall(r"^([\dT:.\-]+Z).*live script: dump:(\w+)", trace, re.M):
                times[label] = int(datetime.fromisoformat(stamp).timestamp() * 1_000_000)
            scene = check.dump(out, "scene") or {}
            me = scene.get("me")
            mock_lines = re.findall(r"^([\dT:.\-]+Z).*crowd mock: (\d+) impostors \(feed (\d+), perceived (\d+)\)", trace, re.M)
            for label, value in arms:
                for stop, _ in (("far", -30), ("middle", 11)):
                    key = f"{label}_{stop}"
                    d = check.dump(out, key) or {}
                    perceived = [i for i in d.get("perceived", []) if i != me]
                    lod = (d.get("extra") or {}).get("lod") or {}
                    view = (d.get("extra") or {}).get("view") or {}
                    lo, hi = times.get(f"{key}_a", 0), times.get(key, 0)
                    iv = frames_between(frames, lo, hi)
                    imps = [int(n) for s, n, _, _ in mock_lines if lo <= int(datetime.fromisoformat(s).timestamp() * 1_000_000) <= hi]
                    results["stills"].append({
                        "kind": kind, "far_cap": label, "stop": stop, "png": os.path.join(out, f"{key}.png"),
                        "perceived": len(perceived), "perceived_fighters": len([i for i in perceived if i in b.ids]),
                        "drawn": lod.get("near", 0) + lod.get("far", 0), "lod": {k: v for k, v in lod.items() if k != "people"},
                        "battle_alive": b.alive_at(hi // 1000) if hi else None,
                        "frame_ms": {"n": len(iv), "p50": iv[len(iv) // 2] if iv else None, "p90": iv[int(len(iv) * .9)] if iv else None,
                                     "p99": iv[min(len(iv) - 1, math.ceil(len(iv) * .99) - 1)] if iv else None},
                        "impostors": (max(imps) if imps else None) if kind == "mock" else None,
                        "view": view})
                    print(json.dumps(results["stills"][-1]), flush=True)
    finally:
        restore = original_cap if original_cap is not None else "0"
        try:
            b.call("set_world_law", ["far_cap", restore])
            results["far_cap_restored"] = restore
        except RuntimeError as e:
            results["far_cap_restore_error"] = str(e)
        b.stop.set()
        keeper.join(5)
        feeder.join(5)
        results["keeper"] = {"bystanders_died": b.others_died, "heals": b.calls, "failed": b.failed, "deaths": b.deaths, "respawned": b.respawned,
                             "alive_min": min((n for _, n in b.timeline), default=None), "alive_max": max((n for _, n in b.timeline), default=None)}
        with open(os.path.join(ev, "battle-stills.json"), "w") as f:
            json.dump(results, f, indent=1)
        print(json.dumps(results["keeper"]), flush=True)


if __name__ == "__main__":
    main()
