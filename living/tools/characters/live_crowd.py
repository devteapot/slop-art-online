#!/usr/bin/env python3
"""What a town's people cost in a connected client: before and after look-1 (docs/LOOK.md §5).

    live_crowd.py --run RUN --out DIR --arm NAME=BINARY[@RUN][:K=V,...] [--arm ...] [--repeat 3]
                  [--still 30] [--far] [--perf FLAGS]

Each arm is the release client at BINARY, with K=V set in its environment (`LIVING_GAME_PERF`
flags such as `nolooks` as `PERF=…`), on the scratch world `verify-RUN`, or the arm's own `@RUN`
(a client built against another module's bindings needs a world of that module). The arms run interleaved, `--repeat` times,
each one through verify-ui's drive.py on the scratch world `verify-RUN`, as a player at its
arrival with the game camera:

1. **Still** (`--still` s, after 3 s to settle): the frame interval's p50 and p99 (`LIVING_GAME_FRAMES`),
   and the last `views:` and `batches:` lines (`LIVING_GAME_PERF=diag`): people's meshes, materials
   and mesh-material pairs in view, and opaque batch sets.
2. **Walking** (three legs of 8 s, so new people come into sight): the longest frame, frames over
   50 ms, and `hitch:` lines (`LIVING_GAME_PERF=hitch=50`) where that frame or one of the two
   before spawned a character or converted meshes: the first-sight hitch.

Memory, sampled every 2 s: the resident size, the physical footprint and the graphics
(IOAccelerator) memory from macOS's `footprint`, each at its peak and steady (the median over the
still window); and the last `assets:` line (main-world meshes, morph targets, CPU-held pictures,
glTF files) and `batches:`'s textures on the GPU. The load average at each run's start and end is recorded:
measure on a quiet machine, and say so. `--far` draws everyone on the full model
(`LIVING_GAME_FAR=1000`). Every run is uncapped (`LIVING_GAME_FPS_CAP=0`; `--fps-cap` to change it).
Writes DIR/live_crowd.json and a table on stdout.
"""
import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import threading
import time

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
DRIVE = os.path.join(ROOT, ".agents/skills/verify-ui/scripts/drive.py")
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def load():
    return float(os.getloadavg()[0])


def pct(xs, p):
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def mac_memory(pid):
    """A process's physical footprint and its IOAccelerator (graphics) memory in MiB, from
    macOS's `footprint` (as crowd.py)."""
    try:
        text = subprocess.run(["footprint", "-p", str(pid)], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return 0, 0
    mib = lambda v, u: float(v) * dict(B=1 / (1 << 20), KB=1 / 1024, MB=1, GB=1024).get(u, 0)
    total = re.search(r"Footprint:\s*([\d.]+)\s*(B|KB|MB|GB)", text)
    gpu = sum(mib(v, u) for v, u, cat in re.findall(r"^\s*([\d.]+)\s*(B|KB|MB|GB)\s+[\d.]+\s*(?:B|KB|MB|GB)\s+[\d.]+\s*(?:B|KB|MB|GB)\s+\d+\s+(.*)$", text, re.M) if "IOAccelerator" in cat)
    return int(mib(*total.groups())) if total else 0, int(gpu)


def peak_rss(pid_file, stop, out):
    """Sample the client's resident size, physical footprint and graphics memory (MiB) every 2 s
    while it runs: (time, rss, footprint, gpu)."""
    while not stop.is_set():
        try:
            pid = int(open(pid_file).read().split()[0])
            rss = int(subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True).stdout.strip() or 0) / 1024
            fp, gpu = mac_memory(pid)
            out[0] = max(out[0], rss)
            out.append((time.time(), rss, fp, gpu))
        except (OSError, ValueError):
            pass
        stop.wait(2.0)


def one(a, arm, binary, env, k, out, run=None):
    name = f"cost-{arm}-{k}"
    run = run or a.run
    d = os.path.join(ROOT, ".local/living/verify", run, "ui", name)
    os.makedirs(d, exist_ok=True)
    frames = os.path.join(d, "frames.csv")
    perf = ",".join(x for x in ["frames", "diag", "hitch=50", a.perf, env.pop("PERF", "")] if x)
    # Uncapped (the headless loop's default is 60 Hz): the frame interval is the frame's cost.
    e = dict(os.environ, LIVING_GAME_FRAMES=frames, LIVING_GAME_PERF=perf, LIVING_GAME_FPS_CAP=a.fps_cap, **env)
    if a.far:
        e["LIVING_GAME_FAR"] = "1000"
    plan = f"ready;wait:3;dump:t0;wait:{a.still};dump:t1;walk:90:8;walk:180:8;walk:270:8;dump:t2;quit"
    load0 = load()
    stop, rss = threading.Event(), [0.0]
    cmd = [sys.executable, DRIVE, "--run", run, "--name", name, "--plan", plan, "--client", binary, "--timeout", "600"]
    p = subprocess.Popen(cmd, env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    # drive.py prints the client's pid first.
    pid_file = os.path.join(d, "pid")
    head = []
    for line in p.stdout:
        head.append(line)
        m = re.search(r"client pid (\d+)", line)
        if m:
            open(pid_file, "w").write(m.group(1))
            break
    t = threading.Thread(target=peak_rss, args=(pid_file, stop, rss), daemon=True)
    t.start()
    rest = "".join(head) + p.stdout.read()
    p.wait()
    stop.set()
    load1 = load()
    mark = {s: os.path.getmtime(os.path.join(d, f"{s}.json")) for s in ("t0", "t1", "t2") if os.path.exists(os.path.join(d, f"{s}.json"))}
    samples = rss[1:]
    steady = [x for x in samples if "t0" in mark and "t1" in mark and mark["t0"] <= x[0] <= mark["t1"]]
    med = lambda xs: round(statistics.median(xs)) if xs else None
    memory = dict(peak_rss_mib=round(rss[0]), peak_footprint_mib=max([x[2] for x in samples] or [0]), peak_gpu_mib=max([x[3] for x in samples] or [0]),
                  steady_rss_mib=med([x[1] for x in steady]), steady_footprint_mib=med([x[2] for x in steady]), steady_gpu_mib=med([x[3] for x in steady]))
    rows = []
    if os.path.exists(frames):
        for ln in open(frames):
            parts = ln.strip().split(",")
            if len(parts) >= 2 and parts[0].isdigit():
                rows.append((int(parts[0]) / 1e6, int(parts[1]) / 1000))
    still = [ms for t_, ms in rows if "t0" in mark and "t1" in mark and mark["t0"] <= t_ <= mark["t1"]]
    walk = [ms for t_, ms in rows if "t1" in mark and "t2" in mark and mark["t1"] < t_ <= mark["t2"]]
    log = ANSI.sub("", open(os.path.join(d, "client.log"), errors="replace").read()) if os.path.exists(os.path.join(d, "client.log")) else ""
    views = [l for l in log.splitlines() if "views:" in l]
    batches = [l for l in log.splitlines() if "batches:" in l]
    assets = [l for l in log.splitlines() if "assets:" in l]
    hitches = [l for l in log.splitlines() if "hitch:" in l]
    # A frame's cost shows in the next frame's delta: a hitch is a first sight when that frame or
    # one of the two before spawned a character or converted its meshes (new materials).
    first_sight = [l for l in hitches if re.search(r"\b[1-9]\d* (characters|converted)\b", l)]
    people = re.search(r"\[people (\d+), (\d+) materials, (\d+)k, (\d+) mesh-material pairs\]", views[-1]) if views else None
    opaque = re.search(r"opaque (\d+) sets", batches[-1]) if batches else None
    r = dict(arm=arm, run=run, k=k, rc=p.returncode, load_start=round(load0, 1), load_end=round(load1, 1),
             still_frames=len(still), p50_ms=pct(still, 50), p99_ms=pct(still, 99),
             walk_frames=len(walk), walk_max_ms=max(walk) if walk else None, walk_over_50=sum(1 for x in walk if x > 50),
             hitches=len(hitches), first_sight_hitches=len(first_sight), first_sight_max_ms=max([float(m.group(1)) for l in first_sight for m in [re.search(r"hitch: ([\d.]+) ms", l)] if m] or [0]) or None,
             people_meshes=int(people.group(1)) if people else None, people_materials=int(people.group(2)) if people else None, people_ktris=int(people.group(3)) if people else None, people_pairs=int(people.group(4)) if people else None,
             opaque_sets=int(opaque.group(1)) if opaque else None, **memory, assets=assets[-1].split("assets:")[-1].strip()[:200] if assets else None,
             gpu_textures=(re.search(r"textures \d+ on the GPU [\d.]+ MiB", batches[-1]) or [None])[0] if batches else None,
             prewarm=next((l.split("loading: ")[-1] for l in log.splitlines() if "prewarm characters" in l), None),
             composed=len(re.findall(r"compose: .* wears", log)), looks_warnings=sorted(set(re.findall(r"looks: [^\n]*", log)))[:6], evidence=d)
    out.append(r)
    print(json.dumps({x: r[x] for x in ("arm", "k", "rc", "p50_ms", "p99_ms", "walk_max_ms", "first_sight_hitches", "people_materials", "people_pairs", "opaque_sets", "peak_rss_mib", "steady_rss_mib", "steady_footprint_mib", "steady_gpu_mib", "load_start")}), flush=True)
    if p.returncode != 0:
        print(rest[-600:], flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--arm", action="append", required=True, help="NAME=BINARY[:K=V,...]")
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--still", type=float, default=30.0)
    ap.add_argument("--far", action="store_true", help="everyone on the full model (LIVING_GAME_FAR=1000)")
    ap.add_argument("--perf", default="", help="more LIVING_GAME_PERF flags for every arm")
    ap.add_argument("--fps-cap", default="0", help="LIVING_GAME_FPS_CAP for every run (default 0: uncapped)")
    a = ap.parse_args()
    arms = []
    for spec in a.arm:
        name, rest = spec.split("=", 1)
        binary, _, kv = rest.partition(":")
        binary, _, run = binary.partition("@")
        env = dict(x.split("=", 1) for x in kv.split(",") if x) if kv else {}
        arms.append((name, binary, env, run or None))
    os.makedirs(a.out, exist_ok=True)
    out = []
    for k in range(a.repeat):
        for name, binary, env, run in (arms if k % 2 == 0 else arms[::-1]):
            one(a, name, binary, dict(env), k, out, run)
    summary = {}
    for name, _, _, _ in arms:
        rs = [r for r in out if r["arm"] == name and r["rc"] == 0 and r["p50_ms"]]
        med = lambda key: statistics.median([r[key] for r in rs if r[key] is not None]) if any(r[key] is not None for r in rs) else None
        summary[name] = {key: med(key) for key in ("p50_ms", "p99_ms", "walk_max_ms", "first_sight_hitches", "first_sight_max_ms", "people_meshes", "people_materials", "people_pairs", "opaque_sets", "peak_rss_mib", "peak_footprint_mib", "peak_gpu_mib", "steady_rss_mib", "steady_footprint_mib", "steady_gpu_mib", "composed")}
        summary[name]["runs"] = len(rs)
        summary[name]["load"] = [min([r["load_start"] for r in rs] or [0]), max([r["load_end"] for r in rs] or [0])]
    json.dump({"run": a.run, "far": a.far, "still_s": a.still, "fps_cap": a.fps_cap, "arms": [(n, b, e, r or a.run) for n, b, e, r in arms], "runs": out, "summary": summary}, open(os.path.join(a.out, "live_crowd.json"), "w"), indent=1)
    for name, s in summary.items():
        print(name, json.dumps(s))


if __name__ == "__main__":
    main()
