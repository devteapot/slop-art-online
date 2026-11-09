"""Batch text-to-motion with NVIDIA Kimodo-SOMA-RP-v1.2, run on the DGX Spark.

Loads the model and its text encoder once, then generates every (clip, seed) of a clip library
(`living/tools/blender/clips.json`) into NPZs. Run from the Spark's Kimodo venv:

    TEXT_ENCODER_MODE=local HF_HUB_OFFLINE=1 python batch.py clips.json OUT_DIR [--only a,b] [--force]

Each library entry with a `prompt` is generated for each of its `seeds` as OUT_DIR/<name>_s<seed>.npz
(Kimodo's own NPZ layout, the 77-joint SOMA skeleton). Existing files are kept unless --force.
OUT_DIR/batch_stats.json records the timings and the exact settings.

An entry may pin its first and last frames to a full-body keyframe, so one-shots start and end
in the same neutral pose the idles use:
    "start": "<pose>", "end": "<pose>"
where <pose> is `neutral` (the library's top-level `neutral`) or `<name>#<seed>@<frame>`: that
frame (negative counts from the end) of an already generated entry, turned to face +Z with its
hips over the origin. `"end_offset": [x, z]` (metres) moves the end keyframe's hips, for moves
that travel. Entries are generated in file order, so a pose must come from an earlier entry.

`"path": [[seconds, x, z], ...]` (metres) pins the hips' ground track on every frame between the
first and last point, linearly between points (Kimodo's Root2DConstraintSet), so a move's travel
follows a given profile: a dodge whose dash the authority performs at a set speed.

Only the SOMA-RP model is used (NVIDIA Open Model License). Never point this at the SMPL-X model.
"""

import argparse
import json
import math
import os
import sys
import time

import numpy as np
import torch

from kimodo import load_model
from kimodo.constraints import FullBodyConstraintSet, Root2DConstraintSet
from kimodo.exports.motion_io import save_kimodo_npz
from kimodo.geometry import matrix_to_axis_angle
from kimodo.tools import seed_everything

MODEL = "Kimodo-SOMA-RP-v1.2"
HIPS, LEFT_LEG, RIGHT_LEG = 0, 67, 72  # somaskel77 indices (SOMA's `Leg` is the thigh joint)


def heading(p):
    """Kimodo's heading of one 77-joint posed frame: 0 faces +Z."""
    d = p[RIGHT_LEG] - p[LEFT_LEG]
    return math.atan2(d[2], -d[0])


def yaw(phi):
    c, s = math.cos(phi), math.sin(phi)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=np.float32)


def pose_ref(spec, neutral, out_dir):
    if spec == "neutral":
        spec = neutral
    name_seed, frame = spec.split("@")
    name, seed = name_seed.split("#")
    d = np.load(os.path.join(out_dir, f"{name}_s{int(seed)}.npz"))
    f = int(frame) % d["local_rot_mats"].shape[0]
    local = d["local_rot_mats"][f].copy()
    p = d["posed_joints"][f]
    root = d["root_positions"][f]
    h = heading(p)
    # Turn about the vertical through the hips until the heading is 0; check the sign numerically.
    for phi in (-h, h):
        R = yaw(phi)
        q = (p - root) @ R.T
        if abs(heading(q)) < 1e-3:
            break
    else:
        raise SystemExit(f"could not face {spec} forward (heading {h})")
    local[HIPS] = R @ local[HIPS]
    return local, float(root[1])


def path_constraint(model, entry, frames, device):
    pts = entry["path"]
    ts = [p[0] for p in pts]
    first, last = round(ts[0] * model.fps), min(round(ts[-1] * model.fps), frames - 1)
    idx = list(range(first, last + 1))
    xz = [[float(np.interp(f / model.fps, ts, [p[1] for p in pts])), float(np.interp(f / model.fps, ts, [p[2] for p in pts]))] for f in idx]
    c = Root2DConstraintSet.from_dict(model.skeleton, {"frame_indices": idx, "smooth_root_2d": xz})
    return c.to(device)


def constraints(model, entry, frames, neutral, out_dir, device):
    keys = []
    path = [path_constraint(model, entry, frames, device)] if entry.get("path") else []
    if entry.get("start"):
        keys.append((0, entry["start"], (0.0, 0.0)))
    if entry.get("end"):
        keys.append((frames - 1, entry["end"], tuple(entry.get("end_offset", (0.0, 0.0)))))
    if not keys:
        return path
    locs, roots, idx = [], [], []
    for f, spec, (ox, oz) in keys:
        local, y = pose_ref(spec, neutral, out_dir)
        locs.append(local)
        roots.append([ox, y, oz])
        idx.append(f)
    aa = matrix_to_axis_angle(torch.from_numpy(np.stack(locs)))
    c = FullBodyConstraintSet.from_dict(model.skeleton, {
        "frame_indices": idx,
        "local_joints_rot": aa.tolist(),
        "root_positions": roots,
    })
    return [c.to(device)] + path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("library")
    ap.add_argument("out")
    ap.add_argument("--only", default="", help="comma-separated entry names")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    lib = json.load(open(a.library))
    only = {x for x in a.only.split(",") if x}
    os.makedirs(a.out, exist_ok=True)
    device = "cuda:0"
    steps = lib.get("steps", 100)
    cfg = lib.get("cfg", [2.0, 2.0])
    t0 = time.time()
    model = load_model(MODEL, device=device)
    torch.cuda.synchronize()
    t_load = time.time() - t0
    print(f"LOAD {MODEL} {t_load:.1f} s", flush=True)
    runs = []
    for e in lib["clips"]:
        if "prompt" not in e or (only and e["name"] not in only):
            continue
        frames = round(e["seconds"] * model.fps)
        for seed in e["seeds"]:
            path = os.path.join(a.out, f"{e['name']}_s{seed}.npz")
            if os.path.exists(path) and not a.force:
                continue
            cons = constraints(model, e, frames, lib.get("neutral"), a.out, device)
            seed_everything(seed)
            torch.cuda.synchronize()
            t1 = time.time()
            out = model([e["prompt"]], [frames], steps, multi_prompt=True, constraint_lst=cons,
                        cfg_weight=cfg, num_samples=1, post_processing=True, return_numpy=True,
                        progress_bar=lambda x, **k: x)
            torch.cuda.synchronize()
            dt = time.time() - t1
            single = {k: (v[0] if hasattr(v, "shape") and v.ndim > 0 and v.shape[0] == 1 else v) for k, v in out.items()}
            save_kimodo_npz(path, single)
            runs.append({"name": e["name"], "seed": seed, "frames": frames, "constraints": len(cons) > 0, "generate_s": round(dt, 2)})
            print(f"GEN {e['name']} seed {seed}: {frames} frames, {dt:.2f} s{' (keyframed)' if cons else ''}", flush=True)
    stats = {
        "model": MODEL, "steps": steps, "cfg": cfg, "post_processing": True,
        "load_s": round(t_load, 1), "total_s": round(time.time() - t0, 1),
        "peak_cuda_allocated_gib": round(torch.cuda.max_memory_allocated() / 2**30, 2),
        "runs": runs,
    }
    if runs:
        g = [r["generate_s"] for r in runs]
        stats["generate_s_mean"] = round(sum(g) / len(g), 2)
        stats["generate_s_per_motion_second"] = round(sum(g) / sum(r["frames"] / model.fps for r in runs), 3)
    prev = os.path.join(a.out, "batch_stats.json")
    hist = json.load(open(prev)) if os.path.exists(prev) else []
    hist.append(stats)
    json.dump(hist, open(prev, "w"), indent=1)
    print(json.dumps({k: v for k, v in stats.items() if k != "runs"}))


if __name__ == "__main__":
    main()
