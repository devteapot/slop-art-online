#!/usr/bin/env python3
"""What a crowd of generated people costs in the game: frame time, triangles, materials, draws
and memory, with every person a different file, at the game camera.

    python3 living/tools/characters/crowd.py TOWN_DIR OUT_DIR [--count 64] [--seconds 24] [--size 1600x900]
                                             [--runs empty,vroid,ours[,far][,same]] [--set NAME=TOWN_DIR ...]
                                             [--repeat N] [--perf FLAGS] [--springs 0|1] [--tag=-NAME]

TOWN_DIR is a town made by town.py (its `town.json` names the people; their models are
lookdev/anim/own-<name>.glb). The people stand in the game's own crowd (`LIVING_GAME_CROWD`,
characters.rs `spawn_crowd`) in an environment (`--env`, default `meadow`: open ground, so the
people are what is measured; `cullet` is the grey city with its own walkers), seen by the
default game camera (22 m, 28° down), each playing its idle clip. Three runs, each in a fresh process, uncapped:

- `ours`: --count generated people, each a different file;
- `far` (not run by default): the same people's far models (lookdev/far/own-<name>.glb, town.py
  --lod near,far). At the game camera everyone is beyond 10 m, so this is what a client that
  switches models by distance would draw;
- any `--set NAME=TOWN_DIR`: another town's people under that name, and `NAME-far` their far
  models. Name a run twice in --runs to interleave two sets (`--runs old,new,new,old`);
- `same` (not run by default): --count generated people, all one file, to tell what many
  different files cost from what many people cost;
- `vroid`: the same count of the VRoid bases the game used before (two files, recoloured);
- `empty`: the same scene with no crowd.

No change to the game is needed: the crowd draws its bases from recipes.json's `bases`, so for
the `ours` run this writes a temporary recipes.json whose list puts a different person at each
index the crowd's seeded draws land on (the draws are reproduced here: characters.rs `Rng` and
`Recipe::random_in`), with neutral proportions and no recolouring. The file is restored
afterwards. The log's own lines say which file each character took; the count of distinct
files is checked and reported.

Read from the game's log: `people perf` (frame time, LIVING_GAME_PERF=frames), `view … meshes`
(LIVING_GAME_PERF=diag: meshes, distinct meshes and materials, triangles per view) and the spring
bones' cost. Memory is the process's peak resident size (/proc), and the GPU's memory in use
(the kernel's per-process DRM counters). On macOS the resident size is `ps`'s and the graphics
memory the process's IOAccelerator memory from `footprint` (sampled every few seconds; the peak
of the samples), and its physical footprint is reported too. OUT_DIR gets `crowd.json`, the logs
and a photograph of each run.

`lod` and `NAME-lod` runs (not by default) use the people's files holding the full and the far
model (lookdev/lod/own-<name>.glb, town.py --lod both), which a client that switches by
distance (lookdev.rs `far_models`) draws as one or the other. `--binary NAME=PATH` runs a set
with another build of the game (`--runs before:ours,lod`: the `before` binary for `ours`), and
`--game-env K=V` sets a variable for every run.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
RECIPES = os.path.join(REPO, "living", "game", "assets", "characters", "recipes.json")
M = (1 << 64) - 1


class Rng:
    """characters.rs `Rng` (splitmix64)."""

    def __init__(self, s):
        self.s = s & M

    def next(self):
        self.s = (self.s + 0x9E3779B97F4A7C15) & M
        z = self.s
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & M
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & M
        return z ^ (z >> 31)


def base_draw(seed, folk):
    """The draw `Recipe::random_in` picks its base with, when no palette has a colour: two draws
    for build, nine for proportions, then the base."""
    h = 0
    for c in folk.encode():
        h = (h * 131 + c) & M
    r = Rng(((seed * 0x2545F4914F6CDD1D) & M) ^ h)
    for _ in range(11):
        r.next()
    return r.next()


def crowd_slots(n, seed):
    """Each crowd member's folk and seed, in spawn order (characters.rs `spawn_crowd`)."""
    giants = max(n // 7, 1 if n >= 3 else 0)
    small = max(n // 5, 1 if n >= 2 else 0)
    adults = max(n - giants - small, 0)
    out = []
    for folk, count in (("small", small), ("adult", adults), ("giant", giants)):
        for _ in range(count):
            out.append((folk, seed * 1000 + len(out)))
    return out


def book_for(people, n, sub=""):
    """A recipe book whose crowd of n is n different people: the bases list and the crowd's seed.
    `sub` is the models' folder under lookdev/ (`far/` for the far models)."""
    files = [f"lookdev/{sub}own-{p['name']}.glb" for p in people]
    for length in (4093, 8191, 16381):
        for seed in range(1, 400):
            idx = [base_draw(s, folk) % length for folk, s in crowd_slots(n, seed)]
            if len(set(idx)) == n:
                bases = [files[0]] * length
                # Children take the crowd's small slots (it spawns those first).
                kids = [f for f, p in zip(files, people) if p["params"]["age"] < 16]
                grown = [f for f, p in zip(files, people) if p["params"]["age"] >= 16]
                order = (kids + grown)[:n] if len(kids) <= n // 5 else kids[: n // 5] + grown + kids[n // 5 :]
                order = (order * (n // len(order) + 1))[:n]
                for i, f in zip(idx, order):
                    bases[i] = f
                return bases, seed
    raise SystemExit("no crowd seed gives every member a different base")


def gpu_memory(pid):
    """A process's graphics memory in MiB, from the kernel's per-client DRM counters
    (/proc/<pid>/fdinfo: `drm-memory-*` or `drm-total-*`, each client counted once)."""
    seen, total = set(), 0
    try:
        for fd in os.listdir(f"/proc/{pid}/fdinfo"):
            try:
                text = open(f"/proc/{pid}/fdinfo/{fd}").read()
            except OSError:
                continue
            client = re.search(r"drm-client-id:\s*(\d+)", text)
            if not client or client.group(1) in seen:
                continue
            seen.add(client.group(1))
            for key, value, unit in re.findall(r"drm-(?:memory|total)-(\w+):\s*(\d+)\s*(\w*)", text):
                if key in ("vram", "gtt", "memory", "system"):
                    total += int(value) * dict(KiB=1024, MiB=1 << 20, GiB=1 << 30).get(unit, 1)
    except OSError:
        pass
    return total // (1 << 20)


def mac_memory(pid):
    """A process's physical footprint and its IOAccelerator (graphics) memory in MiB, from
    macOS's `footprint`."""
    try:
        text = subprocess.run(["footprint", "-p", str(pid)], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return 0, 0
    mib = lambda v, u: float(v) * dict(B=1 / (1 << 20), KB=1 / 1024, MB=1, GB=1024).get(u, 0)
    total = re.search(r"Footprint:\s*([\d.]+)\s*(B|KB|MB|GB)", text)
    gpu = sum(mib(v, u) for v, u, cat in re.findall(r"^\s*([\d.]+)\s*(B|KB|MB|GB)\s+[\d.]+\s*(?:B|KB|MB|GB)\s+[\d.]+\s*(?:B|KB|MB|GB)\s+\d+\s+(.*)$", text, re.M) if "IOAccelerator" in cat)
    return int(mib(*total.groups())) if total else 0, int(gpu)


def run_game(out, name, env, seconds, size, place="meadow", photo=True, binary=None):
    """Run the game headless on the line-up for `seconds`, logging; returns what was measured."""
    log = os.path.join(out, f"{name}.log")
    shots = os.path.join(out, name)
    shutil.rmtree(shots, ignore_errors=True)
    target = os.environ.get("CARGO_TARGET_DIR", os.path.join(REPO, "living", "target"))
    binary = binary or os.path.join(target if os.path.isabs(target) else os.path.join(REPO, target), "release", "living-game")
    # The tour photographs once per shot; each shot waits for the scene to settle, so a list of
    # shots keeps the run going while the log gathers its two-second reports.
    e = dict(os.environ, LIVING_GAME_LOOKDEV="1", LIVING_GAME_TOUR=shots, LIVING_GAME_TOUR_ONLY=place, LIVING_GAME_TOUR_SHOTS=",".join(["default"] * 400), LIVING_GAME_SIZE=size,
             LIVING_GAME_FPS_CAP="0", LIVING_GAME_FRAMES=os.path.join(out, f"{name}.frames.csv"), RUST_LOG="warn,living_game=debug", **env)
    e.setdefault("LIVING_GAME_PERF", "frames,diag")
    peak = dict(rss=0, gpu=0, footprint=0)
    with open(log, "w") as f:
        p = subprocess.Popen([binary], cwd=os.path.join(REPO, "living", "game"), env=e, stdout=f, stderr=subprocess.STDOUT)

        def watch():
            while p.poll() is None:
                if sys.platform == "darwin":
                    try:
                        peak["rss"] = max(peak["rss"], int(subprocess.run(["ps", "-o", "rss=", "-p", str(p.pid)], capture_output=True, text=True).stdout.strip() or 0) // 1024)
                    except ValueError:
                        pass
                    fp, gpu = mac_memory(p.pid)
                    peak["footprint"], peak["gpu"] = max(peak["footprint"], fp), max(peak["gpu"], gpu)
                    time.sleep(2.0)
                    continue
                try:
                    for line in open(f"/proc/{p.pid}/status"):
                        if line.startswith("VmRSS:"):
                            peak["rss"] = max(peak["rss"], int(line.split()[1]) // 1024)
                except OSError:
                    pass
                peak["gpu"] = max(peak["gpu"], gpu_memory(p.pid))
                time.sleep(1.0)

        t = threading.Thread(target=watch, daemon=True)
        t.start()
        try:
            p.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            p.terminate()
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
        t.join(timeout=3)
    text = open(log, errors="replace").read()
    res = dict(run=name, rss_mb=peak["rss"], gpu_mb=peak["gpu"], binary=binary)
    if peak["footprint"]:
        res["footprint_mb"] = peak["footprint"]
    lods = re.findall(r"(\d+) of (\d+) with a far model show it", re.sub(r"\x1b\[[0-9;]*m", "", text))
    if lods:
        res.update(far_shown=int(lods[-1][0]), with_far=int(lods[-1][1]))
    perf = [(float(a), float(b), int(c)) for a, b, c in re.findall(r"people perf: mean ([\d.]+) ms \([\d.]+ fps\), worst ([\d.]+) ms; (\d+) characters", text)]
    # The first reports include loading; the settled ones are the second half.
    settled = perf[len(perf) // 2 :] if len(perf) >= 4 else perf
    if settled:
        res.update(frame_ms=round(sum(a for a, _, _ in settled) / len(settled), 2), worst_ms=max(b for _, b, _ in settled), characters=settled[-1][2], reports=len(perf))
    files = re.findall(r"characters: (\S+) has (\d+) spring joints", text)
    res.update(files=len(set(f for f, _ in files)), spring_joints=sum(int(n) for _, n in files))
    clean = re.sub(r"\x1b\[[0-9;]*m", "", text)
    views = re.findall(r"views: (\d+) toon materials; main (\d+) meshes \((\d+) distinct, (\d+) materials\) (\d+)k tris \[people (\d+), (\d+) materials, (\d+)k\]; cascade0 (\d+) meshes \((\d+) distinct, (\d+) materials\) (\d+)k tris", clean)
    if views:
        v = [int(x) for x in views[-1]]
        res.update(toon_materials=v[0], main_meshes=v[1], main_distinct_meshes=v[2], main_materials=v[3], main_ktris=v[4], people_meshes=v[5], people_materials=v[6], people_ktris=v[7],
                   cascade_meshes=v[8], cascade_materials=v[10], cascade_ktris=v[11], cascades=len(re.findall(r"cascade\d+ ", clean.split("views:")[-1].splitlines()[0])))
    last = [m for m in re.findall(r"diag: (render/.*)", clean)]
    if last:
        gpu = {k.strip(): float(v) for k, v in (kv.rsplit(" ", 1) for kv in last[-1].split(";") if kv.strip()) if k.strip().endswith("elapsed_gpu") or k.strip().endswith("elapsed_cpu")}
        res["gpu_ms"] = round(sum(v for k, v in gpu.items() if k.endswith("elapsed_gpu")), 2)
        res["passes_gpu_ms"] = {k.split("/")[1]: round(v, 2) for k, v in gpu.items() if k.endswith("elapsed_gpu") and v >= 0.1}
    sp = re.findall(r"springs: ([\d.]+) characters \((\d+) joints\) a frame, (\d+) µs a frame", clean)
    if sp:
        res.update(springs_characters=float(sp[-1][0]), springs_joints=int(sp[-1][1]), springs_us=int(sp[-1][2]))
    an = re.findall(r"anim cost: (\d+) bodies; per frame play (\d+) µs, animation set (\d+) µs, ik (\d+) µs", clean)
    if an:
        res.update(anim_us=sum(int(x) for x in an[-1][1:]))
    # The work the main schedule did each frame, from the per-frame record.
    try:
        rows = [line.split(",") for line in open(e["LIVING_GAME_FRAMES"]) if line[:1].isdigit()]
        rows = rows[len(rows) // 2 :]
        iv = sorted(int(r[1]) for r in rows)
        res.update(frames=len(rows), interval_ms_p50=round(iv[len(iv) // 2] / 1000, 2), interval_ms_p95=round(iv[int(len(iv) * 0.95)] / 1000, 2), interval_ms_p99=round(iv[int(len(iv) * 0.99)] / 1000, 2))
    except (OSError, IndexError, ValueError):
        pass
    shutil.rmtree(shots, ignore_errors=True)
    if not photo:
        return res
    # The photograph: the same scene once more, left to take its one shot and quit.
    e2 = dict(e, LIVING_GAME_TOUR_SHOTS="default", LIVING_GAME_PERF="", LIVING_GAME_FPS_CAP="60", RUST_LOG="warn")
    e2.pop("LIVING_GAME_FRAMES", None)
    try:
        subprocess.run([binary], cwd=os.path.join(REPO, "living", "game"), env=e2, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
    except subprocess.TimeoutExpired:
        pass
    pics = sorted(x for x in os.listdir(shots) if x.endswith(".png")) if os.path.isdir(shots) else []
    if pics:
        keep = os.path.join(out, f"{name}.png")
        shutil.copy(os.path.join(shots, pics[-1]), keep)
        res["picture"] = keep
    shutil.rmtree(shots, ignore_errors=True)
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("town")
    ap.add_argument("out")
    ap.add_argument("--count", type=int, default=64)
    ap.add_argument("--seconds", type=float, default=24)
    ap.add_argument("--size", default="1600x900")
    ap.add_argument("--runs", default="empty,vroid,ours")
    ap.add_argument("--set", action="append", default=[], metavar="NAME=TOWN_DIR", help="another town's people as a run of that name (and NAME-far, their far models)")
    ap.add_argument("--perf", default="", help="more LIVING_GAME_PERF flags for every run (e.g. nooutlines)")
    ap.add_argument("--springs", default="", help="LIVING_GAME_SPRINGS for every run (0 turns spring bones off)")
    ap.add_argument("--repeat", type=int, default=1, help="run the whole list this many times, interleaved; frame times are then reported as median, least and most (a shared machine's load moves them)")
    ap.add_argument("--tag", default="", help="a suffix for this set of runs' names")
    ap.add_argument("--binary", action="append", default=[], metavar="NAME=PATH", help="a build of the game a run can name (`--runs NAME:set`)")
    ap.add_argument("--game-env", action="append", default=[], metavar="K=V", help="an environment variable for every run")
    ap.add_argument("--env", default="meadow", help="the environment the crowd stands in (envs/<id>.json; `lineup` is the look-dev line-up, which also shows every file in lookdev/)")
    a = ap.parse_args()
    people = json.load(open(os.path.join(a.town, "town.json")))["people"]
    sets = {"ours": (people, ""), "same": (people, ""), "far": (people, "far/"), "lod": (people, "lod/")}
    for item in a.set:
        name, town = item.split("=", 1)
        other = json.load(open(os.path.join(town, "town.json")))["people"]
        sets[name], sets[name + "-far"], sets[name + "-lod"] = (other, ""), (other, "far/"), (other, "lod/")
    binaries = dict(b.split("=", 1) for b in a.binary)
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    extra = dict(kv.split("=", 1) for kv in a.game_env)
    if a.perf:
        extra["LIVING_GAME_PERF"] = "frames,diag," + a.perf
    if a.springs:
        extra["LIVING_GAME_SPRINGS"] = a.springs
    original = open(RECIPES).read()
    results, rounds = [], {}

    def one(run, photo):
        build, _, name = run.rpartition(":")
        if build and build not in binaries:
            raise SystemExit(f"--runs {run}: no --binary {build}=PATH")
        binary = binaries.get(build)
        label = run.replace(":", "-") + a.tag
        if name == "empty":
            return run_game(out, label, extra, a.seconds, a.size, a.env, photo, binary)
        if name == "vroid":
            return run_game(out, label, dict(extra, LIVING_GAME_CROWD=f"{a.count}:1"), a.seconds, a.size, a.env, photo, binary)
        if name in sets:
            book = json.loads(original)
            who, sub = sets[name]
            missing = [p["name"] for p in who if not os.path.exists(os.path.join(REPO, "living", "game", "assets", "lookdev", sub, f"own-{p['name']}.glb"))]
            if missing:
                raise SystemExit(f"--runs {name}: no model lookdev/{sub}own-{missing[0]}.glb ({len(missing)} missing)")
            bases, seed = book_for(who, a.count, sub)
            if name == "same":
                # Everyone the same file: what the people cost when nothing differs between them.
                grown = next(p for p in who if p["params"]["age"] >= 18)
                bases = [f"lookdev/own-{grown['name']}.glb"]
            one_ = dict(height=[1.72, 1.72], **{k: [1.0, 1.0] for k in ("legs", "arms", "torso", "neck", "head", "shoulders", "hips", "build", "hands", "feet")})
            small = dict(one_, height=[1.25, 1.25], head=[1.2, 1.2])
            book.update(bases=bases, folks=dict(adult=one_, giant=one_, small=small), palettes={k: [] for k in book["palettes"]})
            with open(RECIPES, "w") as f:
                json.dump(book, f)
            try:
                return run_game(out, label, dict(extra, LIVING_GAME_CROWD=f"{a.count}:{seed}"), a.seconds, a.size, a.env, photo, binary)
            finally:
                with open(RECIPES, "w") as f:
                    f.write(original)
        raise SystemExit(f"--runs: {name!r} is not one of empty, vroid, {', '.join(sets)}")

    def load():
        return round(os.getloadavg()[0], 2)

    try:
        for k in range(a.repeat):
            for name in a.runs.split(","):
                before = load()
                r = one(name, photo=name not in rounds)  # each set is photographed once, on its first run
                r["load_average"] = round((before + load()) / 2, 1)
                rounds.setdefault(name, []).append(r)
                print(json.dumps({x: r.get(x) for x in ("run", "frame_ms", "interval_ms_p50", "gpu_ms", "people_materials", "people_meshes", "people_ktris", "rss_mb", "footprint_mb", "gpu_mb", "far_shown", "load_average")}), flush=True)
        for name, rs in rounds.items():
            r = dict(rs[-1])
            for key in ("frame_ms", "interval_ms_p50", "interval_ms_p95", "interval_ms_p99", "gpu_ms", "rss_mb", "footprint_mb", "gpu_mb", "springs_us", "anim_us", "load_average"):
                vals = sorted(x[key] for x in rs if x.get(key) is not None)
                if vals:
                    r[key] = vals[len(vals) // 2]
                    r[key + "_range"] = [vals[0], vals[-1]]
            r["rounds"] = len(rs)
            # Every run of this set in the order it was made, to compare sets round by round.
            r["each"] = [{k: x.get(k) for k in ("frame_ms", "interval_ms_p50", "gpu_ms", "rss_mb", "footprint_mb", "gpu_mb", "load_average")} for x in rs]
            results.append(r)
    finally:
        with open(RECIPES, "w") as f:
            f.write(original)
    path = os.path.join(out, f"crowd{a.tag}.json")
    with open(path, "w") as f:
        json.dump(dict(count=a.count, size=a.size, seconds=a.seconds, perf=a.perf, springs=a.springs, runs=results), f, indent=1)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
