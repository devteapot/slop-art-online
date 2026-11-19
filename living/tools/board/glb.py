"""What a model file holds, measured from the file itself: triangles by part, vertices, bones,
materials, textures, morph targets, clips, glow, bounds and the palette of its vertex colours.

Lifted from the character spike's media.py (`glb_stats`) and generalised to any GLB: buildings,
props and characters. Needs numpy only for the palette.
"""

import hashlib
import json
import math
import os
import struct

COMPONENTS = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read(path):
    """The JSON chunk and the binary chunk of a GLB."""
    b = open(path, "rb").read()
    if b[:4] != b"glTF":
        raise ValueError(f"{path}: not a GLB")
    jl = struct.unpack("<I", b[12:16])[0]
    j = json.loads(b[20 : 20 + jl])
    rest = 20 + jl
    binary = b""
    if rest + 8 <= len(b):
        bl = struct.unpack("<I", b[rest : rest + 4])[0]
        binary = b[rest + 8 : rest + 8 + bl]
    return j, binary, len(b)


def accessor(j, binary, i):
    """One accessor as a numpy array of shape (count, width), normalised integers as floats."""
    import numpy as np

    a = j["accessors"][i]
    if "bufferView" not in a:
        return np.zeros((a["count"], WIDTH[a["type"]]), dtype=np.float32)
    bv = j["bufferViews"][a["bufferView"]]
    fmt, size = COMPONENTS[a["componentType"]]
    width = WIDTH[a["type"]]
    start = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    stride = bv.get("byteStride") or size * width
    dt = np.dtype("<" + fmt)
    raw = np.frombuffer(binary, dtype=np.uint8, count=stride * (a["count"] - 1) + size * width, offset=start)
    if stride == size * width:
        arr = raw.view(dt).reshape(a["count"], width)
    else:
        rows = np.lib.stride_tricks.as_strided(raw, shape=(a["count"], size * width), strides=(stride, 1))
        arr = np.ascontiguousarray(rows).view(dt).reshape(a["count"], width)
    if a.get("normalized") and fmt in "BH":
        return arr.astype(np.float32) / (255.0 if fmt == "B" else 65535.0)
    return arr


def has_glow(j):
    """The game's rule (lookdev.rs `has_glow`): an emissive factor, or a material named *Glow*."""
    for m in j.get("materials", []):
        if any(x > 0.01 for x in m.get("emissiveFactor", [0, 0, 0])) or "Glow" in m.get("name", ""):
            return True
    return False


def _to_srgb(c):
    return [round(255 * (12.92 * x if x <= 0.0031308 else 1.055 * x ** (1 / 2.4) - 0.055)) for x in c]


def palette(j, binary, limit=14, radius=0.075):
    """The model's colours by surface share: each triangle's mean vertex colour (sRGB), weighted
    by its area, grouped greedily into colours within `radius` of each other. Returns
    [{"hex", "share"}] largest first, or None when the model has no vertex colours."""
    import numpy as np

    weights, colours = [], []
    for m in j.get("meshes", []):
        for p in m["primitives"]:
            if p.get("mode", 4) != 4 or "COLOR_0" not in p["attributes"]:
                continue
            pos = accessor(j, binary, p["attributes"]["POSITION"]).astype(np.float64)
            col = accessor(j, binary, p["attributes"]["COLOR_0"]).astype(np.float64)[:, :3]
            idx = accessor(j, binary, p["indices"]).reshape(-1).astype(np.int64) if "indices" in p else np.arange(len(pos))
            tri = idx[: len(idx) // 3 * 3].reshape(-1, 3)
            if not len(tri):
                continue
            a, b, c = pos[tri[:, 0]], pos[tri[:, 1]], pos[tri[:, 2]]
            area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
            mean = col[tri].mean(axis=1).clip(0, 1)
            weights.append(area)
            colours.append(mean)
    if not weights:
        return None
    w = np.concatenate(weights)
    c = np.concatenate(colours)
    srgb = np.where(c <= 0.0031308, 12.92 * c, 1.055 * np.power(c, 1 / 2.4) - 0.055)
    total = float(w.sum()) or 1.0
    # Fine bins first (1/64 of a channel), then greedy grouping of the bins by weight.
    q = np.round(srgb * 63).astype(np.int64)
    key = q[:, 0] * 4096 + q[:, 1] * 64 + q[:, 2]
    uniq, inv = np.unique(key, return_inverse=True)
    binw = np.bincount(inv, weights=w)
    binc = np.stack([np.bincount(inv, weights=w * srgb[:, k]) for k in range(3)], axis=1) / np.maximum(binw[:, None], 1e-12)
    order = np.argsort(-binw)
    groups = []  # [weight, weighted colour sum]
    for i in order:
        col_i, wi = binc[i], binw[i]
        for g in groups:
            if np.linalg.norm(g[1] / g[0] - col_i) < radius:
                g[0] += wi
                g[1] += wi * col_i
                break
        else:
            groups.append([wi, wi * col_i])
    groups.sort(key=lambda g: -g[0])
    out = []
    for g in groups[:limit]:
        r, gg, b = (int(round(255 * x)) for x in (g[1] / g[0]).clip(0, 1))
        out.append({"hex": f"#{r:02x}{gg:02x}{b:02x}", "share": round(g[0] / total, 4)})
    rest = sum(g[0] for g in groups[limit:])
    if rest > 0:
        out.append({"hex": "other", "share": round(rest / total, 4)})
    return out


def stats(path, with_palette=True):
    """Everything the board shows about one file."""
    j, binary, size = read(path)
    acc = j.get("accessors", [])
    parts = {}
    for n in j.get("nodes", []):
        if "mesh" not in n:
            continue
        m = j["meshes"][n["mesh"]]
        t = sum((acc[p["indices"]]["count"] if "indices" in p else acc[p["attributes"]["POSITION"]]["count"]) // 3 for p in m["primitives"])
        parts[n.get("name", "?")] = parts.get(n.get("name", "?"), 0) + t
    verts, seen = 0, set()
    for m in j.get("meshes", []):
        for p in m["primitives"]:
            a = p["attributes"]["POSITION"]
            if a not in seen:
                seen.add(a)
                verts += acc[a]["count"]
    images = j.get("images", [])
    names = [n.get("name", "") for n in j.get("nodes", [])]
    vrm = j.get("extensions", {}).get("VRM", {})
    mats = j.get("materials", [])
    out = dict(
        file=os.path.basename(path),
        sha256=sha256(path),
        bytes=size,
        triangles=sum(parts.values()),
        vertices=verts,
        parts=parts,
        nodes=len(names),
        bones=max((len(s["joints"]) for s in j.get("skins", [])), default=0),
        spring_bones=sum(1 for n in names if n.startswith("J_Sec")),
        materials=[m.get("name") for m in mats],
        textures=len(images),
        texture_bytes=sum(j["bufferViews"][i["bufferView"]]["byteLength"] for i in images if "bufferView" in i),
        morph_targets=max((len(p.get("targets", [])) for m in j.get("meshes", []) for p in m["primitives"]), default=0),
        spring_groups=len(vrm.get("secondaryAnimation", {}).get("boneGroups", [])),
        vertex_colours=bool(j.get("meshes")) and all("COLOR_0" in p["attributes"] for m in j["meshes"] for p in m["primitives"]),
        clips=[a.get("name") for a in j.get("animations", [])],
        glow=has_glow(j),
        glow_triangles=_glow_triangles(j),
    )
    if with_palette:
        try:
            out["palette"] = palette(j, binary)
        except Exception as e:  # a palette is a nicety; a strange file must not stop a publish
            out["palette"] = None
            out["palette_error"] = str(e)[:200]
    return out


def _glow_triangles(j):
    acc = j.get("accessors", [])
    mats = j.get("materials", [])
    glowing = {i for i, m in enumerate(mats) if any(x > 0.01 for x in m.get("emissiveFactor", [0, 0, 0])) or "Glow" in m.get("name", "")}
    n = 0
    for m in j.get("meshes", []):
        for p in m["primitives"]:
            if p.get("material") in glowing:
                n += (acc[p["indices"]]["count"] if "indices" in p else acc[p["attributes"]["POSITION"]]["count"]) // 3
    return n


def palette_delta(old, new, radius=0.075):
    """Match two palettes colour by colour: [{"hex", "old", "new"}] for every colour in either,
    largest change first. Colours within `radius` (sRGB, 0..1) are the same colour."""
    if not old or not new:
        return None

    def rgb(h):
        return [int(h[i : i + 2], 16) / 255 for i in (1, 3, 5)]

    rows, used = [], set()
    for n in new:
        if n["hex"] == "other":
            continue
        best, bd = None, radius
        for k, o in enumerate(old):
            if o["hex"] == "other" or k in used:
                continue
            d = math.dist(rgb(o["hex"]), rgb(n["hex"]))
            if d < bd:
                best, bd = k, d
        if best is None:
            rows.append({"hex": n["hex"], "old": 0.0, "new": n["share"]})
        else:
            used.add(best)
            rows.append({"hex": n["hex"], "old_hex": old[best]["hex"], "old": old[best]["share"], "new": n["share"]})
    for k, o in enumerate(old):
        if o["hex"] != "other" and k not in used:
            rows.append({"hex": o["hex"], "old": o["share"], "new": 0.0})
    rows.sort(key=lambda r: -abs(r["new"] - r["old"]))
    return rows
