#!/usr/bin/env python3
"""Labelled stills of a 200-fighter battle for the owner's attention-budget decision
(docs/ATTENTION_BUDGET.md §5.1, experiment E1; branch `attention-e1`, never merged).

  attention_stills.py --run RUN --cap N [--fighters 200] [--sides 2] [--south 26]
                      [--middle-at 20] [--far-after 4] [--cells 6,4]

RUN is a verify-ui Cullet world (`verify.py launch --run RUN --seed cullet`); one run per arm
(`--cap 0` is the full-view reference). The harness drives the real game client headless (its live
script, as drive.py does) and at each `sync:` step does the scene's part itself:

- `setup`: the world's hour to noon (owner SQL through verify.py, so cleanup knows the epoch),
  `far_cap` to N with `set_world_law` (value-only since law-override; N = 0 leaves it off), the
  player `place_at` the battle's centre (the arrival less 20 m, as `spawn_battle_sides` takes it)
  plus `--south` m due south; the plan then turns the player to face north (`look:0`);
- `battle`: `spawn_battle_sides(fighters, sides)` (the fighters attack only the other side, so
  residents and the player live; docs/BATTLE_LAWS.md §1);
- `pause_mid`: at `--middle-at` s after the spawn the world is paused (`set_paused true`); the crowd
  mock's feed is then built from owner SQL of every `body` (developer truth): the creatures within
  the player's sight radius and field (`applied_gaze`, else `character_senses`; cover ignored),
  each with whether it is fighting (within 2 m of someone of the other side);
- `v_<mode>_<cell>_<stop>`: the feed rewritten with that mode and cell size (`figures`, `discs`, or
  `off` for no crowd) and the battle's centre as the camera's focus; the plan waits for the mock to
  rebuild, dumps, waits a second, dumps and photographs;
- `resume` / `pause_far`: after the Middle stills the plan zooms to Far (the gaze band follows the
  zoom), the world runs `--far-after` s more and is paused again for the Far stills.

Per still: `<stop>-n<N|off>-<mode>[-<cell>m].png` and a JSON beside it with the attended N (the
`far_cap` value in force) and how many the client actually perceived (the dump's `perceived`, less
me), of them fighters and others (residents, animals, with their kinds), the crowd mock's members
and cells (its status file), the creatures in the field, the zoom stop and camera, the gaze band
applied, the fighters alive, the world hour, the battle's ticked seconds, and the client's frame
time between the two dumps (LIVING_GAME_FRAMES, uncapped).
"""
import argparse, json, math, os, re, signal, subprocess, sys, time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import drive  # noqa: E402
from drive import ROOT, V, admin_token, http, load, refresh_lease, require_running, next_sync_wait, stop  # noqa: E402
sys.path.insert(0, os.path.join(ROOT, "living/tools"))
from law_values import own_laws  # noqa: E402

SESSION = "/Users/carlid/dev/slop-art-online/.local/build-slots/session"


class World:
    def __init__(self, run):
        self.run = run
        self.st = load(run)
        self.db = self.st["db"]
        self.token = admin_token()

    def sql(self, q):
        refresh_lease(self.st)
        code, body = http(f"/v1/database/{self.db}/sql", q, self.token, raw=True, timeout=30)
        if code != 200:
            raise RuntimeError(f"sql {q!r}: {code} {body[:300]}")
        res = json.loads(body)[-1]
        names = [e["name"]["some"] if isinstance(e["name"], dict) else e["name"] for e in res["schema"]["elements"]]
        return [dict(zip(names, r)) for r in res["rows"]]

    def call(self, reducer, args):
        refresh_lease(self.st)
        code, body = http(f"/v1/database/{self.db}/call/{reducer}", args, self.token, timeout=60)
        if code != 200:
            raise RuntimeError(f"{reducer}{args}: {code} {body[:300]}")
        return {"reducer": reducer, "args": args, "code": code, "wall_ms": int(time.time() * 1000)}


def pose_end(r):
    """A body's position at its segment's end (`next_ms`): where a client's extrapolation of the
    row comes to rest while the world is paused."""
    from verify_steering import pose
    return pose(r, min(r["next_ms"], r["t_ms"] + 3000))


def facing_end(r):
    """common::facing_at at the segment's end: the travel heading after its turn, plus the facing
    offset after its own turn (`steer::facing`)."""
    t = (min(r["next_ms"], r["t_ms"] + 3000) - r["t_ms"]) / 1000
    h = r["heading"] + (r["turn"] * min(t, r["turn_s"]) if r["turn"] and r["turn_s"] > 0 else 0.0)
    off = r["face_off"] + (r["face_turn"] * min(t, r["face_turn_s"]) if r["face_turn"] and r["face_turn_s"] > 0 else 0.0)
    return math.atan2(math.sin(h + off), math.cos(h + off))


def senses_of(w, me):
    """The player's senses in force: the applied gaze's (a gaze world), else the law's row."""
    keys = ["id", "sight", "hearing", "field", "focal_deg", "side_deg", "side_share", "near_m", "margin_deg", "at_ms"]
    g = w.sql(f"SELECT * FROM applied_gaze WHERE id = {me}")
    if g:
        s = g[0]["senses"]
        s = dict(zip(keys, s)) if isinstance(s, list) else s
        return {"band": g[0]["band"], "ceiling": g[0]["ceiling"], **s}
    s = w.sql(f"SELECT * FROM character_senses WHERE id = {me}")
    return {"band": None, "ceiling": None, **(s[0] if s else {})}


def within(eye, heading, at, s):
    """living_rules::sight::within without glow, keep or the sight line (cover ignored)."""
    dist = math.dist(eye, at)
    bound = lambda r: min(r, s["ceiling"]) if s.get("ceiling") else r
    if not s.get("field"):
        return dist <= bound(s["sight"])
    if dist <= bound(min(s["near_m"], s["sight"])):
        return True
    off = math.atan2(at[1] - eye[1], at[0] - eye[0]) - heading
    off = abs(math.degrees((off + math.pi) % (2 * math.pi) - math.pi))
    ahead = s["sight"] if off <= s["focal_deg"] else (s["sight"] * s["side_share"] if off <= s["side_deg"] else 0.0)
    return dist <= bound(max(ahead, min(s["near_m"], s["sight"])))


def hour_of(w):
    row = w.sql("SELECT epoch_ms, day_ms FROM world")[0]
    day, now = int(row["day_ms"]), int(time.time() * 1000)
    # The world starts at 07:00 (drive.epoch_at).
    return round(((now - int(row["epoch_ms"])) % day) / day * 24 + 7, 2) % 24


def frames_between(path, lo_us, hi_us):
    out = []
    if os.path.exists(path):
        for line in open(path):
            try:
                unix, delta, work = map(int, line.split(","))
            except ValueError:
                continue
            if lo_us < unix < hi_us:
                out.append((delta / 1000, work / 1000))
    return out


def pct(v, p):
    v = sorted(v)
    return round(v[min(len(v) - 1, max(0, math.ceil(len(v) * p) - 1))], 2) if v else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True)
    ap.add_argument("--cap", type=int, required=True, help="far_cap for this arm; 0 = off (the full-view reference)")
    ap.add_argument("--fighters", type=int, default=200)
    ap.add_argument("--sides", type=int, default=2)
    ap.add_argument("--south", type=float, default=26.0)
    ap.add_argument("--middle-at", type=float, default=20.0)
    ap.add_argument("--far-after", type=float, default=4.0)
    ap.add_argument("--cells", default="6,4")
    ap.add_argument("--size", default="1920x1080")
    ap.add_argument("--timeout", type=float, default=900)
    a = ap.parse_args()
    assert a.run.startswith("ui-"), "a verify-ui run"
    arm = f"n{a.cap}" if a.cap else "noff"
    name = f"attention-{arm}"
    w = World(a.run)
    require_running(w.st, w.token)
    out = os.path.join(ROOT, ".local/living/verify", a.run, "ui", name)
    os.makedirs(out, exist_ok=True)
    for f in os.listdir(out):
        if f.endswith(".go"):
            os.remove(os.path.join(out, f))
    feed = os.path.join(out, "crowd-feed.json")
    frames = os.path.join(out, "frames.csv")
    cells = [float(c) for c in a.cells.split(",")]
    variants = [("off", None)] + ([(m, c) for m in ("figures", "discs") for c in cells] if a.cap else [])
    label = lambda stop, mode, cell: f"{stop}-{arm}-{'nocrowd' if mode == 'off' and a.cap else ('full' if mode == 'off' else mode)}" + (f"-{cell:g}m" if cell else "")
    plan = ["ready", "wait:1", "click:@tip:ok", "wait:1", "sync:setup", "wait:3", "look:0", "wait:3", "sync:battle", "sync:pause_mid", "wait:2.5"]
    syncs = ["setup", "battle", "pause_mid"]
    for stop_name in ("middle", "far"):
        if stop_name == "far":
            plan += ["notches:-30", "wait:2", "sync:resume", "sync:pause_far", "wait:2.5"]
            syncs += ["resume", "pause_far"]
        for mode, cell in variants:
            k = label(stop_name, mode, cell)
            s = f"v_{k}".replace("-", "_").replace(".", "_")
            plan += [f"sync:{s}", "wait:1.5", f"dump:{k}_a", "wait:1", f"dump:{k}", f"shot:{k}"]
            syncs.append(s)
    plan += ["sync:done", "quit"]
    syncs.append("done")
    open(os.path.join(out, "plan.txt"), "w").write(";\n".join(plan) + "\n")
    with open(feed, "w") as f:
        json.dump({"seq": 0, "mode": "off", "cell": 6.0, "bodies": []}, f)

    client = os.path.join(os.environ.get("CARGO_TARGET_DIR", os.path.join(ROOT, ".local/target")), "release/living-game")
    token = os.path.join(ROOT, ".local/living/verify", a.run, "ui", "player.token")
    server = os.environ.get("LIVING_STDB_URL", "http://127.0.0.1:3300")
    env = dict(os.environ, LIVING_SERVER=server, LIVING_DB=w.db, LIVING_GAME_NAME="Verifier", LIVING_GAME_TOKEN=token,
               LIVING_GAME_LIVE=out, LIVING_GAME_LIVE_PLAN=";".join(plan), LIVING_GAME_SIZE=a.size,
               LIVING_GAME_SETTINGS=os.path.join(out, "settings.json"), RUST_LOG=os.environ.get("RUST_LOG", "info,wgpu=warn,naga=warn"),
               LIVING_GAME_DEV_CROWD_MOCK=feed, LIVING_GAME_FRAMES=frames, LIVING_GAME_FPS_CAP="0")
    log_path = os.path.join(out, "client.log")
    p = subprocess.Popen([client], env=env, stdout=open(log_path, "w"), stderr=subprocess.STDOUT, cwd=ROOT)
    print(f"client pid {p.pid}; evidence {out}", flush=True)
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda n, _f: sys.exit(128 + n))

    st = {"run": a.run, "db": w.db, "arm": arm, "far_cap_asked": a.cap, "fighters_asked": a.fighters, "sides": a.sides, "south_m": a.south,
          "client": client, "calls": [], "pauses": {}, "variants": {}}
    state = {"seq": 0, "fighters": set(), "side": {}, "spawn_wall": None, "ticked_before": 0.0, "resumed_wall": None, "bodies": [], "focus": None}
    try:
        st["far_cap_own_before"] = own_laws(w.sql).get("far_cap")
        st["module"] = {k: w.st.get(k) for k in ("commit", "dirty", "script_sha256", "seed", "module_sha256", "wasm") if k in w.st}
        pending = {os.path.join(out, f"{s}.go"): s for s in syncs}
        offset, me, t0 = 0, None, time.time()
        while p.poll() is None:
            if time.time() - t0 > a.timeout:
                print("timeout: stopping the client", flush=True)
                break
            refresh_lease(w.st)
            text = open(log_path, errors="replace").read()
            if me is None:
                m = re.search(r"playing character #(\d+)", text)
                if m:
                    me = int(m.group(1))
                    st["me"] = me
                else:
                    time.sleep(0.4)
                    continue
            s, offset = next_sync_wait(text, offset, pending)
            if s is None:
                time.sleep(0.25)
                continue
            handle(s, a, w, st, state, me, feed, variants, label)
            del pending[os.path.join(out, f"{s}.go")]
            open(os.path.join(out, f"{s}.go"), "w").close()
        p.wait(timeout=60)
        st["client_exit"] = p.returncode
    finally:
        stop(p)
        try:
            w.call("set_paused", [True])
        except RuntimeError as e:
            st["pause_error"] = str(e)
        json.dump(st, open(os.path.join(out, "run.json"), "w"), indent=1, default=list)
    shots = collect(out, st, frames, variants, label, a, arm)
    json.dump({"run": st, "shots": shots}, open(os.path.join(out, "stills.json"), "w"), indent=1, default=list)
    print(json.dumps([{k: s[k] for k in ("still", "perceived", "perceived_fighters", "others_perceived", "crowd_members", "crowd_cells", "fighters_alive", "frame_ms_p50")} for s in shots], indent=0), flush=True)


def wait_session():
    while os.path.isdir(SESSION):
        print("the owner is playing (build-slots/session): waiting", flush=True)
        time.sleep(30)


def handle(s, a, w, st, state, me, feed, variants, label):
    print(f"sync {s}", flush=True)
    if s == "setup":
        wait_session()
        q = f"UPDATE world SET epoch_ms = {drive.epoch_at(a.run, 12)} WHERE id = 0"
        r = subprocess.run([sys.executable, V, "sql", "--run", a.run, q], capture_output=True, text=True)
        st["calls"].append({"sql": q, "code": r.returncode})
        if a.cap:
            st["calls"].append(w.call("set_world_law", ["far_cap", str(a.cap)]))
        land = w.sql("SELECT arrive_x, arrive_y FROM land")[0]
        cx, cy = land["arrive_x"], land["arrive_y"] - 20.0
        st["centre_planned"] = [cx, cy]
        st["calls"].append(w.call("place_at", [me, cx, cy + a.south]))
        time.sleep(0.5)
        b = w.sql(f"SELECT x, y FROM body WHERE id = {me}")[0]
        st["player_at"] = [b["x"], b["y"]]
        st["law_change"] = w.sql("SELECT * FROM law_change")[-3:]
    elif s == "battle":
        wait_session()
        before = {r["id"] for r in w.sql("SELECT id FROM character")}
        st["calls"].append(w.call("spawn_battle_sides", [a.fighters, a.sides]))
        state["spawn_wall"] = time.time()
        rows = w.sql("SELECT id, name FROM character")
        for r in rows:
            if r["id"] not in before:
                state["fighters"].add(r["id"])
                state["side"][r["id"]] = r["name"][:1]
        bodies = [r for r in w.sql("SELECT id, x, y FROM body") if r["id"] in state["fighters"]]
        state["focus"] = [sum(r["x"] for r in bodies) / len(bodies), sum(r["y"] for r in bodies) / len(bodies)]
        st["fighters_spawned"] = len(state["fighters"])
        st["fighter_ids"] = sorted(state["fighters"])
        st["centre"] = state["focus"]
        print(f"battle: {len(state['fighters'])} fighters, centre {state['focus']}", flush=True)
    elif s in ("pause_mid", "pause_far"):
        if s == "pause_mid":
            due = state["spawn_wall"] + a.middle_at
        else:
            due = state["resumed_wall"] + a.far_after
        time.sleep(max(0.0, due - time.time()))
        st["calls"].append(w.call("set_paused", [True]))
        ticked = (state["ticked_before"] + (time.time() - (state["resumed_wall"] or state["spawn_wall"])))
        state["ticked_before"] = ticked
        time.sleep(0.6)
        snapshot(s, w, st, state, me, ticked)
    elif s == "resume":
        st["calls"].append(w.call("set_paused", [False]))
        state["resumed_wall"] = time.time()
    elif s.startswith("v_"):
        k = next(label(stop, m, c) for stop in ("middle", "far") for m, c in variants if f"v_{label(stop, m, c)}".replace("-", "_").replace(".", "_") == s)
        mode, cell = next((m, c) for stop in ("middle", "far") for m, c in variants if label(stop, m, c) == k)
        state["seq"] += 1
        with open(feed + ".tmp", "w") as f:
            json.dump({"seq": state["seq"], "mode": mode, "cell": cell or 6.0, "focus": state["frame"], "focus_at": 0.85, "hide_ui": True, "bodies": state["bodies"]}, f)
        os.replace(feed + ".tmp", feed)
        st["variants"][k] = {"seq": state["seq"], "mode": mode, "cell": cell, "pause": state["pause"]}
    elif s == "done":
        pass


def snapshot(s, w, st, state, me, ticked):
    """While paused: who is where (segment ends), the player's senses and the in-field set."""
    chars = {r["id"]: r for r in w.sql("SELECT id, name, kind, alive FROM character")}
    rows = w.sql("SELECT id, x, y, vx, vy, t_ms, next_ms, heading, turn, turn_s, face_off, face_turn, face_turn_s FROM body")
    pos = {r["id"]: pose_end(r) for r in rows if chars.get(r["id"], {}).get("alive")}
    mine = next(r for r in rows if r["id"] == me)
    eye, heading = pos.get(me, (mine["x"], mine["y"])), facing_end(mine)
    sen = senses_of(w, me)
    alive_f = [i for i in state["fighters"] if i in pos]
    bodies = []
    for i, at in pos.items():
        if i == me or not within(eye, heading, at, sen):
            continue
        fighting = False
        if i in state["side"]:
            fighting = any(j != i and state["side"].get(j) not in (None, state["side"][i]) and math.dist(at, pos[j]) <= 2.0 for j in alive_f)
        bodies.append({"id": i, "x": round(at[0], 2), "y": round(at[1], 2), "fighting": fighting, "fighter": i in state["side"], "kind": chars[i]["kind"]})
    state["bodies"] = bodies
    state["pause"] = s
    # The frame: the battle's near (south) edge, the 95th percentile of the fighters' y, at 85% of
    # the picture's height on its centre line, at the battle's centre x (README: why not the
    # centre on the middle).
    fy = sorted(pos[i][1] for i in alive_f)
    near_y = fy[min(len(fy) - 1, int(len(fy) * 0.95))] if fy else state["focus"][1]
    state["frame"] = [state["focus"][0], round(near_y + 0.5, 2)]
    st["pauses"][s] = {
        "wall_ms": int(time.time() * 1000), "battle_ticked_s": round(ticked, 2), "world_hour": hour_of(w),
        "fighters_alive": len(alive_f), "player_at": list(eye), "player_heading_deg": round(math.degrees(heading), 1),
        "player_hp": (w.sql(f"SELECT hp, max_hp FROM vitals WHERE id = {me}") or [{}])[0],
        "senses": sen, "in_field": len(bodies), "in_field_fighters": sum(1 for b in bodies if b["fighter"]),
        "in_field_others": sum(1 for b in bodies if not b["fighter"]), "far_cap": own_laws(w.sql).get("far_cap"),
        "frame_near_edge": state["frame"], "frame_at": 0.85,
        "residents_dead_total": sum(1 for c in chars.values() if not c["alive"] and c["id"] not in state["side"]),
        "body_ids_in_field": [b["id"] for b in bodies],
    }
    print(f"{s}: {json.dumps({k: v for k, v in st['pauses'][s].items() if k != 'body_ids_in_field'})}", flush=True)
    st["kinds"] = {i: c["kind"] for i, c in chars.items()}


def collect(out, st, frames, variants, label, a, arm):
    trace = re.sub(r"\x1b\[[0-9;]*m", "", open(os.path.join(out, "client.log"), errors="replace").read())
    times = {}
    for stamp, k in re.findall(r"^([\dT:.\-]+Z).*live script: dump:(\S+)", trace, re.M):
        times[k] = int(datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp() * 1_000_000)
    me = st.get("me")
    fighters = set(st.get("fighter_ids", []))
    shots = []
    status_lines = re.findall(r"crowd mock: seq (\d+) (\w+) cell ([\d.]+) m: (\d+) members in (\d+) cells \(feed (\d+), perceived (\d+)\)", trace)
    for stop_name, pause in (("middle", "pause_mid"), ("far", "pause_far")):
        pz = st["pauses"].get(pause, {})
        for mode, cell in variants:
            k = label(stop_name, mode, cell)
            dpath = os.path.join(out, f"{k}.json")
            d = json.load(open(dpath)) if os.path.exists(dpath) else {}
            ids = [i for i in d.get("perceived", []) if i != me]
            kinds = st.get("kinds", {})
            others = [i for i in ids if i not in fighters]
            okinds = {}
            for i in others:
                okinds[kinds.get(i, "?")] = okinds.get(kinds.get(i, "?"), 0) + 1
            seq = st["variants"].get(k, {}).get("seq")
            mock = [l for l in status_lines if int(l[0]) == seq]
            last = mock[-1] if mock else None
            fr = frames_between(frames, times.get(f"{k}_a", 0), times.get(k, 0))
            extra = d.get("extra") or {}
            shot = {
                "still": f"{k}.png", "arm": arm, "attended_n": a.cap or None, "far_cap_in_force": pz.get("far_cap"),
                "mode": "full view" if not a.cap else ("no crowd" if mode == "off" else mode),
                "cell_m": cell, "zoom_stop": stop_name, "camera": extra.get("view"), "gaze_band_applied": (pz.get("senses") or {}).get("band"),
                "perceived": len(ids),
                "perceived_fighters": len(ids) - len(others),
                "others_perceived": len(others), "others_perceived_kinds": okinds,
                "in_field": pz.get("in_field"), "in_field_fighters": pz.get("in_field_fighters"), "in_field_others": pz.get("in_field_others"),
                "crowd_members": int(last[3]) if last else None, "crowd_cells": int(last[4]) if last else None,
                "crowd_feed": int(last[5]) if last else None, "crowd_mock_perceived": int(last[6]) if last else None,
                "fighters_alive": pz.get("fighters_alive"), "battle_ticked_s": pz.get("battle_ticked_s"), "world_hour": pz.get("world_hour"),
                "residents_dead_total": pz.get("residents_dead_total"),
                "drawn_lod": {kk: vv for kk, vv in (extra.get("lod") or {}).items() if kk != "people"},
                "frame_ms_n": len(fr), "frame_ms_p50": pct([f for f, _ in fr], .5), "frame_ms_p90": pct([f for f, _ in fr], .9),
                "frame_ms_p99": pct([f for f, _ in fr], .99), "work_ms_p50": pct([w for _, w in fr], .5),
                "perceived_ids": ids,
            }
            shots.append(shot)
    return shots


if __name__ == "__main__":
    main()
