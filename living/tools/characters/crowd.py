#!/usr/bin/env python3
"""What a crowd of generated people costs in the game: frame time, triangles, materials, draws
and memory, with every person a different file, at the game camera.

    python3 living/tools/characters/crowd.py TOWN_DIR OUT_DIR [--count 64] [--seconds 24] [--size 1600x900]
                                             [--runs ours,vroid,empty] [--perf FLAGS] [--springs 0|1]

TOWN_DIR is a town made by town.py (its `town.json` names the people; their models are
lookdev/anim/own-<name>.glb). The people stand in the game's own crowd (`LIVING_GAME_CROWD`,
characters.rs `spawn_crowd`) in an environment (`--env`, default `meadow`: open ground, so the
people are what is measured; `cullet` is the grey city with its own walkers), seen by the
default game camera (22 m, 28° down), each playing its idle clip. Three runs, each in a fresh process, uncapped:

- `ours`: --count generated people, each a different file;
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
(the kernel's per-process DRM counters). OUT_DIR gets `crowd.json`, the logs and a photograph of each run.
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


def book_for(people, n):
    """A recipe book whose crowd of n is n different people: the bases list and the crowd's seed."""
    files = [f"lookdev/own-{p['name']}.glb" for p in people]
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


def run_game(out, name, env, seconds, size, place="meadow"):
    """Run the game headless on the line-up for `seconds`, logging; returns what was measured."""
    log = os.path.join(out, f"{name}.log")
    shots = os.path.join(out, name)
    shutil.rmtree(shots, ignore_errors=True)
    target = os.environ.get("CARGO_TARGET_DIR", os.path.join(REPO, "living", "target"))
    binary = os.path.join(target if os.path.isabs(target) else os.path.join(REPO, target), "release", "living-game")
    # The tour photographs once per shot; each shot waits for the scene to settle, so a list of
    # shots keeps the run going while the log gathers its two-second reports.
    e = dict(os.environ, LIVING_GAME_LOOKDEV="1", LIVING_GAME_TOUR=shots, LIVING_GAME_TOUR_ONLY=place, LIVING_GAME_TOUR_SHOTS=",".join(["default"] * 400), LIVING_GAME_SIZE=size,
             LIVING_GAME_FPS_CAP="0", LIVING_GAME_FRAMES=os.path.join(out, f"{name}.frames.csv"), RUST_LOG="warn,living_game=debug", **env)
    e.setdefault("LIVING_GAME_PERF", "frames,diag")
    peak = dict(rss=0, gpu=0)
    with open(log, "w") as f:
        p = subprocess.Popen([binary], cwd=os.path.join(REPO, "living", "game"), env=e, stdout=f, stderr=subprocess.STDOUT)

        def watch():
            while p.poll() is None:
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
    res = dict(run=name, rss_mb=peak["rss"], gpu_mb=peak["gpu"])
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
    ap.add_argument("--perf", default="", help="more LIVING_GAME_PERF flags for every run (e.g. nooutlines)")
    ap.add_argument("--springs", default="", help="LIVING_GAME_SPRINGS for every run (0 turns spring bones off)")
    ap.add_argument("--tag", default="", help="a suffix for this set of runs' names")
    ap.add_argument("--env", default="meadow", help="the environment the crowd stands in (envs/<id>.json; `lineup` is the look-dev line-up, which also shows every file in lookdev/)")
    a = ap.parse_args()
    people = json.load(open(os.path.join(a.town, "town.json")))["people"]
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    extra = {}
    if a.perf:
        extra["LIVING_GAME_PERF"] = "frames,diag," + a.perf
    if a.springs:
        extra["LIVING_GAME_SPRINGS"] = a.springs
    original = open(RECIPES).read()
    results = []
    try:
        for name in a.runs.split(","):
            if name == "empty":
                results.append(run_game(out, name + a.tag, extra, a.seconds, a.size, a.env))
            elif name == "vroid":
                results.append(run_game(out, name + a.tag, dict(extra, LIVING_GAME_CROWD=f"{a.count}:1"), a.seconds, a.size, a.env))
            elif name == "ours":
                book = json.loads(original)
                bases, seed = book_for(people, a.count)
                one = dict(height=[1.72, 1.72], **{k: [1.0, 1.0] for k in ("legs", "arms", "torso", "neck", "head", "shoulders", "hips", "build", "hands", "feet")})
                small = dict(one, height=[1.25, 1.25], head=[1.2, 1.2])
                book.update(bases=bases, folks=dict(adult=one, giant=one, small=small), palettes={k: [] for k in book["palettes"]})
                with open(RECIPES, "w") as f:
                    json.dump(book, f)
                results.append(run_game(out, name + a.tag, dict(extra, LIVING_GAME_CROWD=f"{a.count}:{seed}"), a.seconds, a.size, a.env))
                with open(RECIPES, "w") as f:
                    f.write(original)
            else:
                raise SystemExit(f"--runs: {name!r} is not one of empty, vroid, ours")
            r = results[-1]
            print(json.dumps(r))
    finally:
        with open(RECIPES, "w") as f:
            f.write(original)
    path = os.path.join(out, f"crowd{a.tag}.json")
    with open(path, "w") as f:
        json.dump(dict(count=a.count, size=a.size, seconds=a.seconds, perf=a.perf, springs=a.springs, runs=results), f, indent=1)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
