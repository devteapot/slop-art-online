#!/usr/bin/env python3
"""Check Cullet's asset kit against the plan (docs/SMALL_CITY.md §6, "Checks every model must pass").

    python3 living/tools/cullet_kit_check.py [--kit living/game/assets/envs/cullet] [--again DIR] [--out DIR]

Reads the GLB files themselves (not the generator's own measurements) and the plan
(living/seeds/worlds/cullet/plan.json), and checks each model:

- footprint: nothing above its floor stands more than 0.1 m outside its lot's (or fixture's)
  rectangle. What goes down below the floor (foundations, sea walls, the Fish Steps) is not
  footprint, as buildings.py measures it;
- height: its ridge (the generator's `ridge_m`: the roof, not the chimney pots) is within 0.1 m
  of the plan's `height_m`, for lots;
- doors: every door the generator made is 0.9 x 2.0 m, and the mesh has the leaf's four corners
  where the report says they are;
- triangles: within its budget;
- surfaces: at least 90% of its lit (non-glowing) triangles carry a surface tag (vertex alpha);
- palette: every vertex colour is a palette colour of SMALL_CITY §1 within 0.056 (the jitter of
  0.05 and rounding), or lies between two of them (wear laid over a material);
- materials: only `Body` and `Glow*`;
- the same output from the same seed: with `--again DIR` (a second run of
  `gen_cullet.sh --out DIR`), every file's bytes are equal.

Writes `check.json` and `check.md` to --out (default: the kit's folder) and exits 1 if any model
fails. Standard library only.
"""
import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PALETTE = {
    "basalt": (0.24, 0.25, 0.28), "pale basalt": (0.36, 0.37, 0.39), "limewash": (0.90, 0.89, 0.84), "old lime": (0.78, 0.77, 0.71),
    "slate": (0.30, 0.34, 0.40), "new slate": (0.38, 0.43, 0.50), "lichen": (0.72, 0.66, 0.30), "tar": (0.13, 0.12, 0.12),
    "driftwood": (0.52, 0.50, 0.46), "sooted brick": (0.33, 0.20, 0.17), "new brick": (0.58, 0.30, 0.22), "iron": (0.17, 0.17, 0.19),
    "rust": (0.50, 0.27, 0.15), "verdigris": (0.36, 0.62, 0.55), "bottle green": (0.20, 0.42, 0.30), "amber": (0.78, 0.50, 0.16),
    "aqua": (0.62, 0.80, 0.78), "smoke": (0.55, 0.60, 0.62), "cobalt": (0.16, 0.26, 0.60), "oxblood": (0.45, 0.14, 0.13),
    "mustard": (0.78, 0.60, 0.18), "sea green": (0.22, 0.45, 0.42), "chalk blue": (0.50, 0.62, 0.72), "kelp": (0.30, 0.28, 0.12),
    "sand": (0.86, 0.82, 0.70), "peat": (0.20, 0.15, 0.11), "moor grass": (0.52, 0.50, 0.28), "heather": (0.50, 0.34, 0.48),
}
PAL = list(PALETTE.values())
TOL = 0.056
COMPONENT = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


def srgb(x):
    x = min(1.0, max(0.0, x))
    return 12.92 * x if x <= 0.0031308 else 1.055 * x ** (1 / 2.4) - 0.055


def near_palette(c):
    """2: a palette colour; 1: between two (wear laid over a material); 0: neither."""
    if any(max(abs(a - b) for a, b in zip(c, q)) <= TOL for q in PAL):
        return 2
    for i, a in enumerate(PAL):
        for b in PAL[i + 1:]:
            d = [y - x for x, y in zip(a, b)]
            l2 = sum(x * x for x in d) or 1e-9
            t = min(1.0, max(0.0, sum((p - x) * y for p, x, y in zip(c, a, d)) / l2))
            if max(abs(x + y * t - p) for p, x, y in zip(c, a, d)) <= TOL:
                return 1
    return 0


def read_glb(path):
    """Triangles of a GLB: [(material name, positions[(x, y, z)] in Blender axes, colours[(r, g, b, a)] sRGB, triangle count)]."""
    data = path.read_bytes()
    n = struct.unpack_from("<I", data, 12)[0]
    doc = json.loads(data[20:20 + n])
    binary = memoryview(data)[20 + n + 8:]

    def accessor(i):
        a = doc["accessors"][i]
        v = doc["bufferViews"][a["bufferView"]]
        fmt, size = COMPONENT[a["componentType"]]
        w = WIDTH[a["type"]]
        off = v.get("byteOffset", 0) + a.get("byteOffset", 0)
        stride = v.get("byteStride", size * w)
        if stride == size * w:
            flat = struct.unpack_from(f"<{a['count'] * w}{fmt}", binary, off)
        else:
            flat = [x for k in range(a["count"]) for x in struct.unpack_from(f"<{w}{fmt}", binary, off + k * stride)]
        if a.get("normalized"):
            scale = {"B": 255.0, "H": 65535.0, "b": 127.0, "h": 32767.0}[fmt]
            flat = [x / scale for x in flat]
        return flat, w

    out = []
    for mesh in doc["meshes"]:
        for prim in mesh["primitives"]:
            pos, _ = accessor(prim["attributes"]["POSITION"])
            # glTF is +Y up with the front on +Z; Blender (and the plan's frame) is +Z up, front -Y.
            positions = [(pos[i], -pos[i + 2], pos[i + 1]) for i in range(0, len(pos), 3)]
            colours = None
            if "COLOR_0" in prim["attributes"]:
                col, w = accessor(prim["attributes"]["COLOR_0"])
                colours = [(col[i], col[i + 1], col[i + 2], col[i + 3] if w == 4 else 1.0) for i in range(0, len(col), w)]
            idx = accessor(prim["indices"])[0] if "indices" in prim else list(range(len(positions)))
            name = doc["materials"][prim["material"]]["name"] if "material" in prim else ""
            out.append((name, positions, colours, idx))
    return out


def check_model(item, rec, path):
    hw, hd = item["size"][0] / 2, item["size"][1] / 2
    prims = read_glb(path)
    tris = lit = tagged = 0
    lo, hi = [1e9, 1e9], [-1e9, -1e9]
    seen, shares = {}, [0, 0, 0]
    mats, corners = set(), []
    low = 0.0
    for name, positions, colours, idx in prims:
        mats.add(name)
        glow = name.startswith("Glow")
        for x, y, z in positions:
            low = min(low, z)
            if z >= 0.02:
                lo[0], lo[1], hi[0], hi[1] = min(lo[0], x), min(lo[1], y), max(hi[0], x), max(hi[1], y)
        corners.extend(positions)
        n = len(idx) // 3
        tris += n
        for t in range(n):
            c = colours[idx[3 * t]] if colours else (1.0, 1.0, 1.0, 1.0)
            if not glow:
                lit += 1
                tagged += c[3] < 0.99
            key = (round(c[0], 3), round(c[1], 3), round(c[2], 3))
            if key not in seen:
                seen[key] = near_palette(tuple(srgb(v) for v in key))
            shares[seen[key]] += 1
    over = max(-hw - lo[0], hi[0] - hw, -hd - lo[1], hi[1] - hd, 0.0)
    out = dict(file=rec["file"], kind=rec["kind"], what=rec["what"], size_m=item["size"], triangles=tris, budget=rec["budget_tris"], above_floor_m=[[round(lo[0], 3), round(lo[1], 3)], [round(hi[0], 3), round(hi[1], 3)]],
               outside_lot_m=round(over, 3), below_floor_m=round(-low, 2), tagged_share=round(tagged / max(lit, 1), 4), palette_share=round(shares[2] / tris, 4), wear_blend_share=round(shares[1] / tris, 4),
               off_palette_share=round(shares[0] / tris, 4), materials=sorted(mats), doors=len(rec.get("doors", [])), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    ok = {}
    ok["footprint"] = over <= 0.1
    ok["triangles"] = tris <= rec["budget_tris"]
    ok["surfaces"] = out["tagged_share"] >= 0.9
    ok["palette"] = shares[0] == 0
    ok["materials"] = all(m == "Body" or m.startswith("Glow") for m in mats)
    if item.get("what") == "lot" and "ridge_m" in rec:
        out["ridge_m"], out["plan_height_m"] = rec["ridge_m"], item["height_m"]
        ok["height"] = abs(rec["ridge_m"] - item["height_m"]) <= 0.1 or item["height_m"] == 0
    doors_ok = True
    for d in rec.get("doors", []):
        if abs(d["width_m"] - 0.9) > 1e-6 or abs(d["height_m"] - 2.0) > 1e-6:
            doors_ok = False
            continue
        c, u = d["at"], d["along"]
        for su in (-1, 1):
            for sz in (-1, 1):
                q = (c[0] + su * u[0] * 0.45, c[1] + su * u[1] * 0.45, c[2] + sz * 1.0)
                # Within 2 cm across and up (the leaf's own joints), 12 cm through the wall.
                thick = lambda p: abs((p[0] - q[0]) * u[1] - (p[1] - q[1]) * u[0])  # noqa: E731
                along = lambda p: abs((p[0] - q[0]) * u[0] + (p[1] - q[1]) * u[1])  # noqa: E731
                if not any(abs(p[2] - q[2]) <= 0.02 and along(p) <= 0.02 and thick(p) <= 0.12 for p in corners):
                    doors_ok = False
    if rec.get("doors"):
        ok["doors"] = doors_ok
    out["checks"] = ok
    out["pass"] = all(ok.values())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kit", default=str(ROOT / "living/game/assets/envs/cullet"))
    ap.add_argument("--again", help="a second generation of the kit (gen_cullet.sh --out DIR): its files must be byte-identical")
    ap.add_argument("--out")
    a = ap.parse_args()
    kit = Path(a.kit)
    plan = json.loads((ROOT / "living/seeds/worlds/cullet/plan.json").read_text())
    report = json.loads((kit / "report.json").read_text())
    items = {l["id"]: dict(l, what="lot") for l in plan["lots"] if l.get("model")}
    items.update({f["id"]: dict(f, what="fixture") for f in plan["fixtures"]})
    results, fails = {}, []
    for id, rec in report["models"].items():
        item = items[id]
        path = kit / rec["file"]
        if "cullet/" + rec["file"] != item["model"]:
            fails.append(f"{id}: written to {rec['file']}, but the plan's model is {item['model']}")
        r = check_model(item, rec, path)
        if a.again:
            other = Path(a.again) / rec["file"]
            r["checks"]["same_seed_same_output"] = other.is_file() and hashlib.sha256(other.read_bytes()).hexdigest() == r["sha256"]
            r["pass"] = all(r["checks"].values())
        results[id] = r
        if not r["pass"]:
            fails.append(f"{id}: " + ", ".join(k for k, v in r["checks"].items() if not v))
    built = set(report["models"])
    boxes = [l["id"] for l in plan["lots"] if l.get("model") and l["id"] not in built and l.get("height_m", 0) > 0]
    waiting = [l["id"] for l in plan["lots"] if l.get("model") and l["id"] not in built and not l.get("height_m", 0) > 0]
    missing_fixtures = [f["id"] for f in plan["fixtures"] if f["id"] not in built]
    names = sorted({k for r in results.values() for k in r["checks"]})
    by_kind = {}
    for id, r in results.items():
        g = by_kind.setdefault(r["kind"], dict(models=0, triangles=0, most=0, budget=r["budget"], fails=0, outside=0.0, tagged=1.0, off=0.0, doors=0))
        g["models"] += 1
        g["triangles"] += r["triangles"]
        g["most"] = max(g["most"], r["triangles"])
        g["fails"] += not r["pass"]
        g["outside"] = max(g["outside"], r["outside_lot_m"])
        g["tagged"] = min(g["tagged"], r["tagged_share"])
        g["off"] = max(g["off"], r["off_palette_share"])
        g["doors"] += r["doors"]
    total = dict(models=len(results), triangles=sum(r["triangles"] for r in results.values()), passed=sum(r["pass"] for r in results.values()),
                 checks={n: [sum(1 for r in results.values() if r["checks"].get(n)), sum(1 for r in results.values() if n in r["checks"])] for n in names},
                 lots_as_grey_boxes=boxes, open_lots_without_models=waiting, fixtures_not_built=missing_fixtures, same_seed=bool(a.again))
    out = Path(a.out) if a.out else kit
    out.mkdir(parents=True, exist_ok=True)
    (out / "check.json").write_text(json.dumps(dict(total=total, by_kind=by_kind, models=results, failures=fails), indent=1) + "\n")
    md = ["# Cullet kit: checks", "", f"{total['passed']} of {total['models']} models pass every check; {total['triangles']} triangles in all.", "",
          "| Check | Pass | Of |", "|---|---:|---:|"] + [f"| {n} | {v[0]} | {v[1]} |" for n, v in total["checks"].items()] + [
          "", "| Kind | Models | Triangles | Largest | Budget | Outside its lot, at most (m) | Tagged, at least | Off palette, at most | Doors | Fail |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    md += [f"| {k} | {g['models']} | {g['triangles']} | {g['most']} | {g['budget']} | {g['outside']:.3f} | {g['tagged']:.3f} | {g['off']:.4f} | {g['doors']} | {g['fails']} |" for k, g in sorted(by_kind.items())]
    md += ["", f"Lots still drawn as grey boxes ({len(boxes)}): " + ", ".join(boxes) + ".", "", f"Open lots without a model ({len(waiting)}): " + ", ".join(waiting) + "."]
    if fails:
        md += ["", "## Failures", ""] + [f"- {f}" for f in fails]
    (out / "check.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
