#!/usr/bin/env python3
"""E1b: the player inside a 200-fighter battle, at its centre and at its edge, for the owner's
attention-budget decision (docs/ATTENTION_BUDGET.md §5.1; branch `attention-e1`, never merged).

  attention_inside.py --run RUN --cap N [--site 540,769] [--square 16] [--first 40] [--step 4]

RUN is a verify-ui Cullet world; one arm per run (`--cap 0` is the full view). At `sync:` steps
the harness, as admin scene setup (no authority change):

- `setup`: noon; `far_cap` N by `set_world_law`; the world paused; `spawn_battle_sides(200, 2)`
  (it takes no position: the arrival less 20 m, on a 6 m road beside a drop); its fighters moved
  with `place_at`, one per tile, onto a `--square` m square of open paving centred at `--site` (the
  arrival plaza: no wall, drop or building in it); the player `place_at` the square's centre; the
  world resumed (battle time 0);
- `recentre` (battle time first − 4 s): the player `place_at` the fighters' centroid now;
- `pause_cm`, `pause_cf`, `pause_em`, `pause_ef`: paused at battle time first, +step, +2·step,
  +3·step: centre-Middle, centre-Far (the plan zooms to Far and the world runs `step` s so the gaze
  band applies), then `edge`: the player `place_at` the battle's south edge (the 95th percentile
  of the fighters' y, at their centroid's x; facing north into it), zoom back to Middle, run,
  pause, and Far again;
- at each pause the crowd mock's feed: every living body in the player's sight field (applied gaze,
  cover ignored), each with its top garment's colour (`look.words.top`'s colour word) and whether
  it is fighting (`activity`: an attack, block or dodge under way, or the victim of an attack);
  figures, 6 m cells; the camera is the play camera (no focus);
- picks: at each Middle pause, one more still with rings: green under each creature the client
  perceives (the authority's `far_cap` pick), orange under each that v2's starting order (those
  fighting, nearest first, then the nearest) would attend and the authority did not.

Per still: `<pos>-<stop>-<arm>.png` (+ `-picks`) and a JSON in `stills.json`.
"""
import argparse, concurrent.futures, json, math, os, random, re, signal, subprocess, sys, threading, time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import drive  # noqa: E402
from drive import ROOT, V, refresh_lease, require_running, next_sync_wait, stop  # noqa: E402
from attention_stills import World, pose_end, facing_end, senses_of, within, hour_of, frames_between, pct, wait_session  # noqa: E402
sys.path.insert(0, os.path.join(ROOT, "living/tools"))
from law_values import own_laws  # noqa: E402

# The seed's top-garment colour words (living/seeds/cullet.json looks: every top names one).
COLOURS = {"green": (74, 128, 62), "black": (40, 40, 44), "blue": (58, 92, 168), "yellow": (214, 178, 52), "red": (176, 52, 44),
           "tan": (184, 150, 108), "navy": (36, 46, 92), "purple": (110, 62, 132), "cream": (232, 222, 192), "white": (236, 236, 232),
           "grey": (128, 128, 132), "gray": (128, 128, 132), "brown": (110, 76, 50), "orange": (214, 118, 44)}
COMBAT = {"attack", "block", "dodge"}


def colour_of(words):
    top = (words[4] if isinstance(words, list) and len(words) > 4 else (words or {}).get("top", "")) or ""
    for w in re.findall(r"[a-z]+", top.lower()):
        if w in COLOURS:
            return w
    return None


class Clock:
    """Battle time: the seconds the world ran since the spawn (paused spans excluded)."""

    def __init__(self):
        self.ran, self.since = 0.0, None

    def resume(self):
        self.since = time.time()

    def pause(self):
        if self.since is not None:
            self.ran += time.time() - self.since
        self.since = None

    def now(self):
        return self.ran + (time.time() - self.since if self.since is not None else 0.0)

    def wait_until(self, t):
        time.sleep(max(0.0, t - self.now()))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True)
    ap.add_argument("--cap", type=int, required=True)
    ap.add_argument("--fighters", type=int, default=200)
    ap.add_argument("--site", default="540,769")
    ap.add_argument("--square", type=int, default=16)
    ap.add_argument("--first", type=float, default=40.0)
    ap.add_argument("--step", type=float, default=4.0)
    ap.add_argument("--cell", type=float, default=6.0)
    ap.add_argument("--size", default="1920x1080")
    ap.add_argument("--timeout", type=float, default=900)
    a = ap.parse_args()
    assert a.run.startswith("ui-")
    arm = f"n{a.cap}" if a.cap else "full"
    w = World(a.run)
    require_running(w.st, w.token)
    out = os.path.join(ROOT, ".local/living/verify", a.run, "ui", f"inside-{arm}")
    os.makedirs(out, exist_ok=True)
    for f in os.listdir(out):
        if f.endswith(".go"):
            os.remove(os.path.join(out, f))
    feed = os.path.join(out, "crowd-feed.json")
    frames = os.path.join(out, "frames.csv")
    shots = [("centre", "middle", "pause_cm"), ("centre", "far", "pause_cf"), ("edge", "middle", "pause_em"), ("edge", "far", "pause_ef")]
    # `place_at` resets the body's heading and the client sends a look only when it changes: the
    # look is cleared and set again after each placement, so the player faces north.
    face = ["look:", "wait:0.5", "look:0", "wait:1"]
    plan = ["ready", "wait:1", "click:@tip:ok", "wait:1", "sync:setup", *face, "sync:recentre", *face]
    syncs = ["setup", "recentre"]
    for i, (pos, stop_name, pz) in enumerate(shots):
        if i == 1 or i == 3:
            plan += ["notches:-30", "wait:2", f"sync:resume_{i}"]
            syncs.append(f"resume_{i}")
        if i == 2:
            plan += ["sync:edge", "notches:11", *face, "wait:1", f"sync:resume_{i}"]
            syncs += ["edge", f"resume_{i}"]
        k = f"{pos}-{stop_name}-{arm}"
        plan += [f"sync:{pz}", "wait:2.5", f"sync:v_{i}", "wait:1.5", f"dump:{k}_a", "wait:1", f"dump:{k}", f"shot:{k}"]
        syncs += [pz, f"v_{i}"]
        if a.cap and stop_name == "middle":
            plan += [f"sync:m_{i}", "wait:1.5", f"dump:{k}-picks", f"shot:{k}-picks"]
            syncs.append(f"m_{i}")
    plan += ["sync:done", "quit"]
    syncs.append("done")
    open(os.path.join(out, "plan.txt"), "w").write(";\n".join(plan) + "\n")
    json.dump({"seq": 0, "mode": "off", "cell": a.cell, "bodies": []}, open(feed, "w"))
    client = os.path.join(os.environ.get("CARGO_TARGET_DIR", os.path.join(ROOT, ".local/target")), "release/living-game")
    token = os.path.join(ROOT, ".local/living/verify", a.run, "ui", "player.token")
    env = dict(os.environ, LIVING_SERVER=os.environ.get("LIVING_STDB_URL", "http://127.0.0.1:3300"), LIVING_DB=w.db, LIVING_GAME_NAME="Verifier",
               LIVING_GAME_TOKEN=token, LIVING_GAME_LIVE=out, LIVING_GAME_LIVE_PLAN=";".join(plan), LIVING_GAME_SIZE=a.size,
               LIVING_GAME_SETTINGS=os.path.join(out, "settings.json"), RUST_LOG=os.environ.get("RUST_LOG", "info,wgpu=warn,naga=warn"),
               LIVING_GAME_DEV_CROWD_MOCK=feed, LIVING_GAME_FRAMES=frames, LIVING_GAME_FPS_CAP="0")
    log_path = os.path.join(out, "client.log")
    p = subprocess.Popen([client], env=env, stdout=open(log_path, "w"), stderr=subprocess.STDOUT, cwd=ROOT)
    print(f"client pid {p.pid}; evidence {out}", flush=True)
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda n, _f: sys.exit(128 + n))
    st = {"run": a.run, "db": w.db, "arm": arm, "far_cap_asked": a.cap, "site": a.site, "square_m": a.square, "calls": [], "pauses": {}, "variants": {},
          "alive_timeline": [], "module": {k: w.st.get(k) for k in ("commit", "dirty", "script_sha256", "seed", "wasm") if k in w.st}}
    state = {"seq": 0, "fighters": set(), "side": {}, "clock": Clock(), "bodies": [], "pause": None, "picks": {}, "out": out}
    sampler_stop = threading.Event()

    def sampler():
        while not sampler_stop.wait(2.0):
            if state["clock"].since is None or not state["fighters"]:
                continue
            try:
                alive = {r["id"] for r in w.sql("SELECT id, alive FROM character") if r["alive"]}
                st["alive_timeline"].append([round(state["clock"].now(), 1), len(state["fighters"] & alive)])
            except Exception as e:  # a slow read under load is not fatal
                print(f"sampler: {e}", flush=True)
    threading.Thread(target=sampler, daemon=True).start()
    try:
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
                if not m:
                    time.sleep(0.4)
                    continue
                me = st["me"] = int(m.group(1))
            s, offset = next_sync_wait(text, offset, pending)
            if s is None:
                time.sleep(0.2)
                continue
            handle(s, a, w, st, state, me, feed, shots, arm)
            del pending[os.path.join(out, f"{s}.go")]
            open(os.path.join(out, f"{s}.go"), "w").close()
        p.wait(timeout=60)
        st["client_exit"] = p.returncode
    finally:
        sampler_stop.set()
        stop(p)
        try:
            w.call("set_paused", [True])
        except RuntimeError as e:
            st["pause_error"] = str(e)
        json.dump(st, open(os.path.join(out, "run.json"), "w"), indent=1, default=list)
    res = collect(out, st, frames, shots, arm, a)
    json.dump({"run": st, "shots": res}, open(os.path.join(out, "stills.json"), "w"), indent=1, default=list)
    for r in res:
        print(json.dumps({k: r[k] for k in ("still", "perceived", "perceived_fighters", "others_perceived", "crowd_members", "crowd_cells", "fighters_alive", "picks_agree", "frame_ms_p50")}), flush=True)


def relocate(w, ids, site, square):
    """Each fighter to its own tile of the square (tile centres), in parallel."""
    cx, cy = site
    x0, y0 = int(cx) - square // 2, int(cy) - square // 2
    tiles = [(x0 + i + 0.5, y0 + j + 0.5) for i in range(square) for j in range(square)]
    random.Random(7).shuffle(tiles)
    jobs = list(zip(sorted(ids), tiles))
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        errs = [e for e in pool.map(lambda j: _place(w, *j), jobs) if e]
    return {"moved": len(jobs) - len(errs), "errors": errs[:5], "square": [x0, y0, square]}


def _place(w, i, at):
    try:
        w.call("place_at", [i, at[0], at[1]])
        return None
    except RuntimeError as e:
        return str(e)[:200]


def handle(s, a, w, st, state, me, feed, shots, arm):
    print(f"sync {s} (battle {state['clock'].now():.1f} s)", flush=True)
    clock = state["clock"]
    if s == "setup":
        wait_session()
        q = f"UPDATE world SET epoch_ms = {drive.epoch_at(a.run, 12)} WHERE id = 0"
        r = subprocess.run([sys.executable, V, "sql", "--run", a.run, q], capture_output=True, text=True)
        st["calls"].append({"sql": q, "code": r.returncode})
        if a.cap:
            st["calls"].append(w.call("set_world_law", ["far_cap", str(a.cap)]))
        st["calls"].append(w.call("set_paused", [True]))
        before = {r["id"] for r in w.sql("SELECT id FROM character")}
        st["calls"].append(w.call("spawn_battle_sides", [a.fighters, 2]))
        # The fixture's two enemy stance records are made with due_ms 0, so housekeeping (1 Hz)
        # expires them at once and the sides stop fighting after about 2 s. Scene setup (owner
        # SQL, while paused, housekeeping idle): they never fall due.
        stances = w.sql("SELECT id, kind, due_ms FROM record")
        st["stances_before"] = stances
        for r in stances:
            if r["kind"] == "stance":
                q = f"UPDATE record SET due_ms = 18446744073709551615 WHERE id = {r['id']}"
                rr = subprocess.run([sys.executable, V, "sql", "--run", a.run, q], capture_output=True, text=True)
                st["calls"].append({"sql": q, "code": rr.returncode})
        st["stances_after"] = w.sql("SELECT id, kind, due_ms FROM record")
        for r in w.sql("SELECT id, name FROM character"):
            if r["id"] not in before:
                state["fighters"].add(r["id"])
                state["side"][r["id"]] = r["name"][:1]
        sx, sy = map(float, a.site.split(","))
        st["relocated"] = relocate(w, state["fighters"], (sx, sy), a.square)
        st["calls"].append(w.call("place_at", [me, sx, sy]))
        st["fighter_ids"] = sorted(state["fighters"])
        st["law_change"] = w.sql("SELECT * FROM law_change")
        st["script_revision"] = w.sql("SELECT name, revision FROM script")
        st["calls"].append(w.call("set_paused", [False]))
        clock.resume()
        print(f"battle: {len(state['fighters'])} fighters, relocated {st['relocated']['moved']}", flush=True)
    elif s == "recentre":
        clock.wait_until(a.first - 4)
        c = centroid(w, state)
        st["calls"].append(w.call("place_at", [me, c[0], c[1]]))
        st["centre_at"] = c
    elif s.startswith("pause_"):
        i = [pz for _, _, pz in shots].index(s)
        clock.wait_until(a.first + a.step * i)
        st["calls"].append(w.call("set_paused", [True]))
        clock.pause()
        time.sleep(0.6)
        snapshot(s, w, st, state, me)
    elif s.startswith("resume_"):
        st["calls"].append(w.call("set_paused", [False]))
        clock.resume()
    elif s == "edge":
        c = centroid(w, state)
        rows = w.sql("SELECT id, x, y, vx, vy, t_ms, next_ms, heading, turn, turn_s FROM body")
        alive = {r["id"] for r in w.sql("SELECT id, alive FROM character") if r["alive"]}
        fy = sorted(pose_end(r)[1] for r in rows if r["id"] in state["fighters"] and r["id"] in alive)
        edge_y = fy[min(len(fy) - 1, int(len(fy) * 0.95))] + 0.5
        st["calls"].append(w.call("place_at", [me, c[0], edge_y]))
        st["edge_at"] = [c[0], edge_y]
    elif s.startswith("v_") or s.startswith("m_"):
        i = int(s[2:])
        pos, stop_name, pz = shots[i]
        state["seq"] += 1
        doc = {"seq": state["seq"], "mode": "figures" if a.cap else "off", "cell": a.cell, "hide_ui": True, "bodies": state["bodies"]}
        if s.startswith("m_"):
            d = json.load(open(os.path.join(state["out"], f"{pos}-{stop_name}-{arm}.json")))
            set_picks(state, [x for x in d.get("perceived", []) if x != me], a.cap)
            pk = state["picks"]
            st["variants"].setdefault("picks", {})[s] = {k: v for k, v in pk.items() if k in ("authority_only", "v2_only")}
            doc["marks"] = [{"x": b["x"], "y": b["y"], "kind": 0} for b in pk["authority_bodies"]] + [{"x": b["x"], "y": b["y"], "kind": 1} for b in pk["v2_only_bodies"]]
        json.dump(doc, open(feed + ".tmp", "w"))
        os.replace(feed + ".tmp", feed)
        st["variants"][s] = {"seq": state["seq"], "pause": pz, "marks": len(doc.get("marks", []))}


def centroid(w, state):
    alive = {r["id"] for r in w.sql("SELECT id, alive FROM character") if r["alive"]}
    rows = [r for r in w.sql("SELECT id, x, y, vx, vy, t_ms, next_ms, heading, turn, turn_s FROM body") if r["id"] in state["fighters"] and r["id"] in alive]
    pts = [pose_end(r) for r in rows]
    return [round(sum(p[0] for p in pts) / len(pts), 2), round(sum(p[1] for p in pts) / len(pts), 2)]


def snapshot(s, w, st, state, me):
    chars = {r["id"]: r for r in w.sql("SELECT id, name, kind, alive FROM character")}
    rows = w.sql("SELECT id, x, y, vx, vy, t_ms, next_ms, heading, turn, turn_s, face_off, face_turn, face_turn_s FROM body")
    pos = {r["id"]: pose_end(r) for r in rows if chars.get(r["id"], {}).get("alive")}
    mine = next(r for r in rows if r["id"] == me)
    eye, heading = pos.get(me, (mine["x"], mine["y"])), facing_end(mine)
    sen = senses_of(w, me)
    looks = {r["id"]: colour_of(r["words"]) for r in w.sql("SELECT id, words FROM look")}
    acts = w.sql("SELECT id, skill, victim FROM activity")
    fighting = {r["id"] for r in acts if r["skill"] in COMBAT} | {r["victim"] for r in acts if r["skill"] in COMBAT and r["victim"]}
    alive_f = [i for i in state["fighters"] if i in pos]
    bodies = []
    for i, at in pos.items():
        if i == me or not within(eye, heading, at, sen):
            continue
        c = looks.get(i)
        bodies.append({"id": i, "x": round(at[0], 2), "y": round(at[1], 2), "fighting": i in fighting, "fighter": i in state["side"],
                       "kind": chars[i]["kind"], "colour": c, "rgb": list(COLOURS[c]) if c else None, "dist": round(math.dist(eye, at), 2)})
    state["bodies"] = bodies
    state["pause"] = s
    # v2's starting order over the field (cover ignored): those fighting, nearest first; then the nearest.
    order = sorted(bodies, key=lambda b: (not b["fighting"], b["dist"]))
    state["order"] = order
    st["pauses"][s] = {
        "wall_ms": int(time.time() * 1000), "battle_s": round(state["clock"].now(), 2), "world_hour": hour_of(w),
        "fighters_alive": len(alive_f), "fighters_dead": len(state["fighters"]) - len(alive_f),
        "residents_dead": sum(1 for c in chars.values() if not c["alive"] and c["id"] not in state["side"] and c["kind"] == "person"),
        "player_at": list(eye), "player_heading_deg": round(math.degrees(heading), 1), "senses": sen,
        "in_field": len(bodies), "in_field_fighters": sum(1 for b in bodies if b["fighter"]), "in_field_fighting": sum(1 for b in bodies if b["fighting"]),
        "coloured": sum(1 for b in bodies if b["colour"]), "colours": {c: sum(1 for b in bodies if b["colour"] == c) for c in sorted({b["colour"] for b in bodies if b["colour"]})},
        "far_cap": own_laws(w.sql).get("far_cap"), "v2_order_ids": [b["id"] for b in order],
        "fighting_ids": sorted(b["id"] for b in bodies if b["fighting"]),
    }
    print(f"{s}: " + json.dumps({k: v for k, v in st["pauses"][s].items() if k not in ("v2_order_ids", "senses", "fighting_ids")}), flush=True)
    st["kinds"] = {i: c["kind"] for i, c in chars.items()}


def set_picks(state, perceived, n):
    """The authority's picks (the client's perceived ids) against v2's order's first n."""
    by = {b["id"]: b for b in state["bodies"]}
    v2 = [b["id"] for b in state["order"][:n]]
    auth = [i for i in perceived if i in by]
    state["picks"] = {"authority_bodies": [by[i] for i in auth], "v2_only_bodies": [by[i] for i in v2 if i not in set(perceived)],
                      "authority_only": [i for i in perceived if i not in set(v2)], "v2_only": [i for i in v2 if i not in set(perceived)]}


def collect(out, st, frames, shots, arm, a):
    trace = re.sub(r"\x1b\[[0-9;]*m", "", open(os.path.join(out, "client.log"), errors="replace").read())
    times = {k: int(datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp() * 1_000_000) for t, k in re.findall(r"^([\dT:.\-]+Z).*live script: dump:(\S+)", trace, re.M)}
    status = re.findall(r"crowd mock: seq (\d+) (\w+) cell ([\d.]+) m: (\d+) members in (\d+) cells \(feed (\d+), perceived (\d+)\)", trace)
    me, fighters, kinds = st.get("me"), set(st.get("fighter_ids", [])), st.get("kinds", {})
    res = []
    for i, (pos, stop_name, pz) in enumerate(shots):
        k = f"{pos}-{stop_name}-{arm}"
        dp = os.path.join(out, f"{k}.json")
        d = json.load(open(dp)) if os.path.exists(dp) else {}
        ids = [x for x in d.get("perceived", []) if x != me]
        others = [x for x in ids if x not in fighters]
        pzd = st["pauses"].get(pz, {})
        order = pzd.get("v2_order_ids", [])
        n = a.cap or len(ids)
        v2 = order[:n]
        seq = st["variants"].get(f"v_{i}", {}).get("seq")
        last = ([l for l in status if int(l[0]) == seq] or [None])[-1]
        fr = frames_between(frames, times.get(f"{k}_a", 0), times.get(k, 0))
        extra = d.get("extra") or {}
        okinds = {}
        for x in others:
            okinds[kinds.get(x, kinds.get(str(x), "?"))] = okinds.get(kinds.get(x, kinds.get(str(x), "?")), 0) + 1
        res.append({
            "still": f"{k}.png", "picks_still": f"{k}-picks.png" if a.cap and stop_name == "middle" else None,
            "arm": arm, "attended_n": a.cap or None, "far_cap_in_force": pzd.get("far_cap"), "position": pos, "zoom_stop": stop_name,
            "mode": "figures" if a.cap else "full view", "cell_m": a.cell if a.cap else None,
            "camera": extra.get("view"), "gaze_band_applied": (pzd.get("senses") or {}).get("band"), "player_at": pzd.get("player_at"),
            "perceived": len(ids), "perceived_fighters": len(ids) - len(others), "others_perceived": len(others), "others_perceived_kinds": okinds,
            "perceived_fighting": sum(1 for x in ids if x in set(pzd.get("fighting_ids", []))),
            "in_field": pzd.get("in_field"), "in_field_fighting": pzd.get("in_field_fighting"),
            "crowd_members": int(last[3]) if last else None, "crowd_cells": int(last[4]) if last else None,
            "fighters_alive": pzd.get("fighters_alive"), "fighters_dead": pzd.get("fighters_dead"), "residents_dead": pzd.get("residents_dead"),
            "battle_s": pzd.get("battle_s"), "world_hour": pzd.get("world_hour"),
            "colours_in_field": pzd.get("colours"), "coloured_in_field": pzd.get("coloured"),
            "v2_first_n": v2, "picks_agree": len(set(v2) & set(ids)) if a.cap else None,
            "authority_only": [x for x in ids if x not in set(v2)] if a.cap else None, "v2_only": [x for x in v2 if x not in set(ids)] if a.cap else None,
            "drawn_lod": {kk: vv for kk, vv in (extra.get("lod") or {}).items() if kk != "people"},
            "frame_ms_n": len(fr), "frame_ms_p50": pct([f for f, _ in fr], .5), "frame_ms_p90": pct([f for f, _ in fr], .9),
            "perceived_ids": ids,
        })
    return res


if __name__ == "__main__":
    main()
