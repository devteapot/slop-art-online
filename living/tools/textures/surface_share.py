#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=2"]
# ///
"""How much of each environment's scenery carries a painted-surface tag (surfaces.py), read from
the generated GLBs' vertex-colour alpha, the way the game's toon shader reads it.

    uv run living/tools/textures/surface_share.py [--envs living/game/assets/envs] [ENV ...]
        [--json OUT] [--untagged N]

For each environment (`<env>.json`), every slot kind's models are taken from `<env>/<kind>/`,
else `shared/<kind>/`, as the game does. A triangle's surface is its first corner's alpha
(the generators write one surface per face). Shares are given two ways: `models` counts each
model file once; `placed` weights each kind by its slot count (scatter `count`, or one per other
slot) and its models' mean triangles, which is closer to what a view holds. Glow materials
(`Glow*`, emissive: their tag only shows in their lit colour) are counted apart as well: the
first share counts every triangle, the second only lit (non-glow) ones. `--untagged N` lists the N largest
untagged groups by material and colour, to find the generator part that makes them.
"""

from __future__ import annotations

import argparse
import json
import struct
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from surfaces import SURFACES, STEPS

COMP = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


def read_glb(path: Path):
    data = path.read_bytes()
    _, _, _ = struct.unpack_from("<III", data, 0)
    jlen, _ = struct.unpack_from("<II", data, 12)
    doc = json.loads(data[20:20 + jlen])
    off = 20 + jlen
    blen, _ = struct.unpack_from("<II", data, off)
    return doc, data[off + 8:off + 8 + blen]


def accessor(doc, binc, i):
    a = doc["accessors"][i]
    bv = doc["bufferViews"][a["bufferView"]]
    dt = np.dtype(COMP[a["componentType"]])
    w = WIDTH[a["type"]]
    start = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    stride = bv.get("byteStride") or dt.itemsize * w
    raw = np.frombuffer(binc, np.uint8, count=stride * (a["count"] - 1) + dt.itemsize * w, offset=start)
    rows = np.lib.stride_tricks.as_strided(raw, shape=(a["count"], dt.itemsize * w), strides=(stride, 1))
    arr = np.ascontiguousarray(rows).view(dt).reshape(a["count"], w).astype(np.float64)
    if a.get("normalized"):
        arr /= np.iinfo(dt).max
    return arr


def model_tris(path: Path):
    """[(material name, n triangles, surface index per triangle (-1 untagged), rgb per triangle)]."""
    doc, binc = read_glb(path)
    mats = [m.get("name", "") for m in doc.get("materials", [])]
    out = []
    for mesh in doc.get("meshes", []):
        for p in mesh["primitives"]:
            if p.get("mode", 4) != 4:
                continue
            idx = accessor(doc, binc, p["indices"])[:, 0].astype(np.int64) if "indices" in p else np.arange(doc["accessors"][p["attributes"]["POSITION"]]["count"])
            first = idx[0::3]
            name = mats[p["material"]] if "material" in p else ""
            if "COLOR_0" in p["attributes"]:
                col = accessor(doc, binc, p["attributes"]["COLOR_0"])
                rgb = col[first, :3]
                a = col[first, 3] if col.shape[1] == 4 else np.ones(len(first))
                k = np.floor(a * STEPS).astype(int)
                k = np.where((k >= 0) & (k < len(SURFACES)), k, -1)
            else:
                rgb = np.ones((len(first), 3))
                k = -np.ones(len(first), int)
            out.append((name, len(first), k, rgb))
    return out


def kind_files(envs: Path, env: str, kind: str):
    for d in (envs / env / kind, envs / "shared" / kind):
        files = sorted(d.glob("*.glb")) + sorted(d.glob("*.gltf"))
        if files:
            return files
    return []


def env_share(envs: Path, env: str, untagged_n: int):
    spec = json.loads((envs / f"{env}.json").read_text())
    kinds = Counter()
    for s in spec.get("slots", []):
        kinds[s["kind"]] += s.get("count", 1) if s.get("rule") == "scatter" else 1
    tot = {"models": Counter(), "placed": Counter()}
    groups = Counter()
    for kind, n in kinds.items():
        files = kind_files(envs, env, kind)
        if not files:
            continue
        per = Counter()
        for f in files:
            for name, ntri, k, rgb in model_tris(f):
                if name.startswith("Glow"):
                    per["glow"] += ntri
                    per["glow_untagged"] += int((k < 0).sum())
                    continue
                for s, c in zip(*np.unique(k, return_counts=True)):
                    per[SURFACES[s] if s >= 0 else "untagged"] += int(c)
                if untagged_n:
                    q = np.round(rgb[k < 0] ** (1 / 2.2) * 20) / 20  # sRGB, 0.05 steps
                    for c, m in zip(*np.unique(q, axis=0, return_counts=True)):
                        groups[(kind, name, tuple(float(x) for x in c))] += int(m)
        tot["models"] += per
        for key, v in per.items():
            tot["placed"][key] += v / len(files) * n
    res = {}
    for how, c in tot.items():
        all_ = sum(c.values())
        all_ -= c["glow_untagged"]
        lit = all_ - c["glow"]
        res[how] = {"triangles": round(all_), "glow": round(c["glow"]),
                    "tagged_share": round(1 - c["untagged"] / lit, 4) if lit else None,
                    "tagged_share_all": round(1 - (c["untagged"] + c["glow_untagged"]) / all_, 4) if all_ else None,
                    "surfaces": {k: round(v) for k, v in sorted(c.items(), key=lambda kv: -kv[1])}}
    res["untagged_groups"] = [{"kind": k, "material": m, "srgb": c, "triangles": n} for (k, m, c), n in groups.most_common(untagged_n)]
    return res


def main():
    root = Path(__file__).resolve().parents[3]
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("envs_ids", nargs="*", metavar="ENV")
    ap.add_argument("--envs", default=str(root / "living/game/assets/envs"))
    ap.add_argument("--json", default="")
    ap.add_argument("--untagged", type=int, default=0)
    a = ap.parse_args()
    envs = Path(a.envs)
    ids = a.envs_ids or sorted(p.stem for p in envs.glob("*.json") if p.stem != "island")
    report = {}
    for env in ids:
        r = env_share(envs, env, a.untagged)
        report[env] = r
        m, p = r["models"], r["placed"]
        print(f"{env:16s} tagged: {m['tagged_share_all']:.1%} of all triangles ({m['triangles']:,}), {m['tagged_share']:.1%} of lit ones (glow {m['glow']:,});"
              f" placed {p['tagged_share_all']:.1%} / {p['tagged_share']:.1%}")
        for g in r["untagged_groups"]:
            print(f"    untagged {g['triangles']:7,}  {g['kind']:14s} {g['material']:16s} srgb {g['srgb']}")
    if a.json:
        Path(a.json).write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
