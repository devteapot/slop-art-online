#!/usr/bin/env python3
"""Sanity-check the foot-down markers of every looping gait in animated character files.

    python3 living/tools/marker_check.py FILE.glb [FILE.glb ...] [--json OUT]

Each file's sidecar (`<file>.clips.json`, from `animate.py`, `wolf.py` or `deer.py`) lists every
clip's contact windows per foot, in normalised clip time (`gait.rs` blends gaits on them, `ik.rs`
plants feet by them). A messy take gives bad markers; this reads the markers and the baked take
(the GLB's own animation, sampled here without Blender) and reports, per looping gait (a looping
clip with a speed):

- **missing**: the clip or a foot has no contact window. This is an error: the run fails.
- **windows**: a foot has more than one contact per cycle (a window split at the loop's seam is
  one contact).
- **share**: a foot's share of the cycle on the ground is far from the gait's expected range.
- **pair**: left and right touchdowns are not about half a cycle apart (people; an animal's fore
  pair and hind pair in a walk or trot; a gallop or bound has none to check).
- **sync**: phase 0 is not the synced foot's touchdown (`sync` in the sidecar; people's right
  foot), so blended gaits would not share a footfall.
- **length**: the baked clip is not as long as the sidecar says (markers and the game's phase
  are in the sidecar's time; the wolf's were 1.25 × long, baked at Blender's default 24 fps).
- **slide**: a planted foot moves more than a few cm over its window in the baked take, against
  the ground passing under an in-place gait at the clip's speed. People's feet are measured at
  the slower of the heel (under the ankle, a quarter of a foot behind it) and the ball of the foot
  (heel down, then the ball); an animal's at its
  paw tip (`paw_tips` in the sidecar; the paw bone's head without it).

Everything but missing markers is a warning, so a new clip still gets built. Thresholds are in
[`GAITS`] and the constants below. Prints a summary line per character and per gait clip.
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from pathlib import Path

# Expected share of the cycle each foot is down, by family and gait, and whether left and right
# (an animal's fore pair, hind pair) come down half a cycle apart.
GAITS = {
    ("people", "walk"): {"share": (0.55, 0.65), "pair": True},
    ("people", "sneak"): {"share": (0.55, 0.75), "pair": True},
    ("people", "walk_brisk"): {"share": (0.50, 0.62), "pair": True},
    ("people", "run"): {"share": (0.30, 0.40), "pair": True},
    ("people", "run_fast"): {"share": (0.25, 0.38), "pair": True},
    ("animal", "walk"): {"share": (0.55, 0.70), "pair": True},
    ("animal", "trot"): {"share": (0.35, 0.50), "pair": True},
    # A gallop or bound: paws of a pair land close together, not half a cycle apart.
    ("animal", "run"): {"share": (0.22, 0.40), "pair": False},
}
# A gait not in the table: walking or running by its speed (m/s at stride 1).
DEFAULT = {"walk": {"share": (0.50, 0.70), "pair": True}, "run": {"share": (0.22, 0.42), "pair": True}}
WALK_MAX = 2.8
# How far outside the expected share counts as far (share of the cycle).
SHARE_MARGIN = 0.08
# Left and right touchdowns: half a cycle apart, within this (share of the cycle).
PAIR_TOL = 0.10
# Phase 0 within this of the synced foot's touchdown (share of the cycle), or a frame and a half.
SYNC_TOL = 0.04
# The baked clip may differ from the sidecar's length by this much (s).
LENGTH_TOL = 0.02
# A planted foot may move this far over its window (m).
SLIDE_M = 0.04
SAMPLE_FPS = 60

# People's files are fitted to this height in the game; their sidecar speeds are in its metres
# (`animate.py --height`).
PEOPLE_HEIGHT_M = 1.75
PEOPLE_FEET = {"L": ("J_Bip_L_Foot", "J_Bip_L_ToeBase"), "R": ("J_Bip_R_Foot", "J_Bip_R_ToeBase")}
ANIMAL_FEET = ("fl", "fr", "hl", "hr")
PAIRS = {"people": [("L", "R")], "animal": [("fl", "fr"), ("hl", "hr")]}


# ---- glTF sampling (no Blender, no numpy) ---------------------------------------------------


def qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx, aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz)


def qrot(q, v):
    x, y, z, w = q
    vx, vy, vz = v
    # v + 2w (q×v) + 2 q×(q×v)
    cx, cy, cz = y * vz - z * vy, z * vx - x * vz, x * vy - y * vx
    cx2, cy2, cz2 = y * cz - z * cy, z * cx - x * cz, x * cy - y * cx
    return (vx + 2 * (w * cx + cx2), vy + 2 * (w * cy + cy2), vz + 2 * (w * cz + cz2))


def qslerp(a, b, t):
    d = sum(x * y for x, y in zip(a, b))
    if d < 0:
        b, d = tuple(-x for x in b), -d
    if d > 0.9995:
        r = tuple(x + (y - x) * t for x, y in zip(a, b))
    else:
        th = math.acos(min(1.0, d))
        s0, s1 = math.sin((1 - t) * th) / math.sin(th), math.sin(t * th) / math.sin(th)
        r = tuple(s0 * x + s1 * y for x, y in zip(a, b))
    n = math.sqrt(sum(x * x for x in r)) or 1.0
    return tuple(x / n for x in r)


class Trs:
    """A transform as translation, rotation (x, y, z, w) and scale; composes and applies."""

    def __init__(self, t=(0.0, 0.0, 0.0), r=(0.0, 0.0, 0.0, 1.0), s=(1.0, 1.0, 1.0)):
        self.t, self.r, self.s = tuple(t), tuple(r), tuple(s)

    def apply(self, p):
        q = qrot(self.r, tuple(a * b for a, b in zip(p, self.s)))
        return tuple(a + b for a, b in zip(q, self.t))

    def then(self, child):
        """This transform's frame, then the child's local one (non-uniform scale ignored past one level)."""
        return Trs(self.apply(child.t), qmul(self.r, child.r), tuple(a * b for a, b in zip(self.s, child.s)))

    def inverse_apply(self, p):
        x = tuple(a - b for a, b in zip(p, self.t))
        ri = (-self.r[0], -self.r[1], -self.r[2], self.r[3])
        x = qrot(ri, x)
        return tuple(a / b for a, b in zip(x, self.s))


COMPONENTS = {5126: ("f", 4), 5123: ("H", 2), 5121: ("B", 1), 5125: ("I", 4), 5122: ("h", 2), 5120: ("b", 1)}
WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


class Glb:
    def __init__(self, path):
        data = Path(path).read_bytes()
        magic, _, _ = struct.unpack_from("<4sII", data, 0)
        if magic != b"glTF":
            raise ValueError(f"{path}: not a GLB")
        off, self.json, self.bin = 12, None, b""
        while off < len(data):
            n, kind = struct.unpack_from("<I4s", data, off)
            chunk = data[off + 8: off + 8 + n]
            if kind == b"JSON":
                self.json = json.loads(chunk)
            elif kind == b"BIN\x00":
                self.bin = chunk
            off += 8 + n
        j = self.json
        self.nodes = j["nodes"]
        self.parent = {}
        for i, n in enumerate(self.nodes):
            for c in n.get("children", []):
                self.parent[c] = i
        self.names = {n.get("name", ""): i for i, n in enumerate(self.nodes)}
        self.rest = [Trs(n.get("translation", (0, 0, 0)), n.get("rotation", (0, 0, 0, 1)), n.get("scale", (1, 1, 1))) for n in self.nodes]

    def height(self):
        """The model's height (file units): its meshes' rest vertices' span in y."""
        lo, hi = math.inf, -math.inf
        for i, n in enumerate(self.nodes):
            if "mesh" not in n:
                continue
            sy = rest_world(self, i).s[1]
            ty = rest_world(self, i).t[1]
            for prim in self.json["meshes"][n["mesh"]]["primitives"]:
                a = self.json["accessors"][prim["attributes"]["POSITION"]]
                if "min" in a and "max" in a:
                    lo, hi = min(lo, ty + a["min"][1] * sy), max(hi, ty + a["max"][1] * sy)
        return hi - lo if hi > lo else 1.0

    def accessor(self, i):
        a = self.json["accessors"][i]
        bv = self.json["bufferViews"][a["bufferView"]]
        fmt, size = COMPONENTS[a["componentType"]]
        w = WIDTH[a["type"]]
        stride = bv.get("byteStride", size * w)
        base = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
        out = []
        for k in range(a["count"]):
            v = struct.unpack_from("<" + fmt * w, self.bin, base + k * stride)
            if a.get("normalized"):
                v = tuple(max(x / {"b": 127, "B": 255, "h": 32767, "H": 65535}[fmt], -1.0) for x in v)
            out.append(v if w > 1 else v[0])
        return out

    def animation(self, name):
        """Channels of a named animation: node -> path -> (times, values, interpolation)."""
        for a in self.json.get("animations", []):
            if a.get("name") == name:
                ch = {}
                for c in a["channels"]:
                    s = a["samplers"][c["sampler"]]
                    t = c["target"]
                    if "node" not in t:
                        continue
                    ch.setdefault(t["node"], {})[t["path"]] = (self.accessor(s["input"]), self.accessor(s["output"]), s.get("interpolation", "LINEAR"))
                return ch
        return None

    def chain(self, node):
        out = []
        while node is not None:
            out.append(node)
            node = self.parent.get(node)
        return out[::-1]


def sample(track, t, path):
    times, vals, interp = track
    if interp == "CUBICSPLINE":
        vals = vals[1::3]
    if t <= times[0]:
        return vals[0]
    if t >= times[-1]:
        return vals[-1]
    lo, hi = 0, len(times) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if times[mid] <= t:
            lo = mid
        else:
            hi = mid
    if interp == "STEP":
        return vals[lo]
    f = (t - times[lo]) / max(times[hi] - times[lo], 1e-9)
    if path == "rotation":
        return qslerp(vals[lo], vals[hi], f)
    return tuple(a + (b - a) * f for a, b in zip(vals[lo], vals[hi]))


def world(glb, anim, node, t):
    """A node's world transform at time `t` of an animation (rest where it has no channel)."""
    m = Trs()
    for n in glb.chain(node):
        r = glb.rest[n]
        ch = anim.get(n, {})
        local = Trs(sample(ch["translation"], t, "translation") if "translation" in ch else r.t,
                    sample(ch["rotation"], t, "rotation") if "rotation" in ch else r.r,
                    sample(ch["scale"], t, "scale") if "scale" in ch else r.s)
        m = m.then(local)
    return m


def rest_world(glb, node):
    m = Trs()
    for n in glb.chain(node):
        m = m.then(glb.rest[n])
    return m


# ---- markers ----------------------------------------------------------------------------------


def merged(wins):
    """A foot's contacts as (start, length) per cycle, joining a window that runs to 1 with one
    that starts at 0 (one contact split at the seam)."""
    ws = sorted((a, b) for a, b in wins if b > a)
    if len(ws) >= 2 and ws[0][0] <= 1e-4 and ws[-1][1] >= 1 - 1e-4:
        first, last = ws.pop(0), ws.pop()
        return [(a, b - a) for a, b in ws] + [(last[0], (last[1] - last[0]) + (first[1] - first[0]))]
    return [(a, b - a) for a, b in ws]


def circ(a, b):
    d = (a - b) % 1.0
    return min(d, 1 - d)


def gait_rule(family, clip, speed):
    rule = GAITS.get((family, clip))
    if rule:
        return rule
    return DEFAULT["walk" if (speed or 0) < WALK_MAX else "run"]


def clips_of(side):
    """(family, sync foot, {clip: record}) from a sidecar of either shape."""
    if isinstance(side.get("clips"), list):
        return "animal", side, {c["name"]: c for c in side["clips"] if "name" in c}
    return "people", side, {k: v for k, v in side.items() if isinstance(v, dict)}


def check_file(path):
    path = Path(path)
    side_path = path.with_suffix(".clips.json")
    if not side_path.exists():
        return {"file": path.name, "errors": [f"no sidecar {side_path.name}"], "warnings": [], "clips": []}
    side = json.loads(side_path.read_text())
    family, top, clips = clips_of(side)
    glb = Glb(path)
    feet = list(PEOPLE_FEET) if family == "people" else list(ANIMAL_FEET)
    # Where each foot is measured: (node, offset in its frame) per measured point.
    points = {}
    for f in feet:
        if family == "people":
            ankle, ball = (glb.names.get(n) for n in PEOPLE_FEET[f])
            if ankle is None or ball is None:
                points[f] = []
                continue
            # The heel: under the ankle at the ball's height, a quarter of the foot behind it, in
            # the foot's frame (the foot pivots on it after touchdown; it is not a joint).
            a, b = rest_world(glb, ankle), rest_world(glb, ball)
            heel = (a.t[0] - 0.25 * (b.t[0] - a.t[0]), b.t[1], a.t[2] - 0.25 * (b.t[2] - a.t[2]))
            points[f] = [(ankle, a.inverse_apply(heel)), (ball, (0.0, 0.0, 0.0))]
        else:
            node = glb.names.get(f"paw.{f}")
            tip = (top.get("paw_tips") or {}).get(f)
            off = rest_world(glb, node).inverse_apply(tuple(tip)) if (tip and node is not None) else (0.0, 0.0, 0.0)
            points[f] = [(node, off)]
    # File units per sidecar metre: people are fitted to a height; animals are made in metres.
    unit = glb.height() / float(top.get("height_m") or PEOPLE_HEIGHT_M) if family == "people" else 1.0
    report = {"file": path.name, "family": family, "unit": round(unit, 4), "errors": [], "warnings": [], "clips": []}
    gaits = [(n, c) for n, c in clips.items() if c.get("loop") is not False and (c.get("speed") or 0) > 0.1]
    if not gaits:
        report["errors"].append("no looping gait with a speed in the sidecar")
    for name, c in gaits:
        report["clips"].append(check_clip(glb, family, top, name, c, feet, points, unit))
    for c in report["clips"]:
        report["errors"] += [f"{c['clip']}: {e}" for e in c["errors"]]
        report["warnings"] += [f"{c['clip']}: {w}" for w in c["warnings"]]
    return report


def check_clip(glb, family, top, name, c, feet, points, unit):
    out = {"clip": name, "errors": [], "warnings": [], "share": {}, "slide_cm": {}}
    # The speed the clip is baked at (m/s at playback rate 1).
    speed = c.get("speed") or c.get("natural_speed") or 0.0
    rule = gait_rule(family, name, speed)
    contacts = c.get("contacts") or {}
    wins = {}
    for f in feet:
        if not points.get(f):
            out["errors"].append(f"foot {f}: no such bones in the file")
            continue
        m = merged(contacts.get(f) or [])
        if not m:
            out["errors"].append(f"foot {f} has no contact window")
            continue
        wins[f] = m
        if len(m) > 1:
            out["warnings"].append(f"foot {f} has {len(m)} contacts per cycle")
        share = sum(ln for _, ln in m)
        out["share"][f] = round(share, 3)
        lo, hi = rule["share"]
        if share < lo - SHARE_MARGIN or share > hi + SHARE_MARGIN:
            out["warnings"].append(f"foot {f} down {share:.0%} of the cycle (expected {lo:.0%}-{hi:.0%})")
    if out["errors"]:
        return out
    # Left and right half a cycle apart.
    if rule["pair"]:
        for a, b in PAIRS[family]:
            d = (wins[a][0][0] - wins[b][0][0]) % 1.0
            out.setdefault("pair", {})[f"{a}/{b}"] = round(d, 3)
            if abs(d - 0.5) > PAIR_TOL:
                out["warnings"].append(f"{a} and {b} touch down {d:.2f} of a cycle apart (expected 0.5)")
    # Phase 0 is the synced foot's touchdown.
    sync = c.get("sync") or ("R" if family == "people" else "hl")
    frames = max(2, round((c.get("seconds") or 1.0) * 30))
    tol = max(SYNC_TOL, 1.5 / frames)
    td = min((a for a, _ in wins[sync]), key=lambda a: circ(a, 0.0))
    out["sync"] = f"{sync}@{td:.3f}"
    if circ(td, 0.0) > tol:
        out["warnings"].append(f"phase 0 is not {sync}'s touchdown ({sync} comes down at {td:.3f})")
    # Slide over each window, in the baked take.
    anim = glb.animation(name)
    if anim is None:
        out["warnings"].append("no animation of that name in the file: slide not measured")
        return out
    secs = max((v[0][-1] for ch in anim.values() for v in ch.values()), default=c.get("seconds") or 1.0)
    said = c.get("seconds") or secs
    out["seconds"] = [round(secs, 3), said]
    if abs(secs - said) > LENGTH_TOL:
        out["warnings"].append(f"baked clip is {secs:.3f} s, the sidecar says {said:.3f} s")
    # The ground passes the sidecar's metres per cycle (speed × its seconds) over the baked cycle.
    speed = speed * said / secs * unit
    n = max(8, round(secs * SAMPLE_FPS))
    track = {f: [[world(glb, anim, node, secs * k / n).apply(off) for node, off in points[f] if node is not None] for k in range(n + 1)] for f in feet}
    # The body's forward: against the planted feet's mean drift (gaits are baked in place).
    drift = [0.0, 0.0]
    for f in feet:
        for a, ln in wins[f]:
            k0, k1 = round(a * n), round((a + ln) * n)
            p0, p1 = track[f][k0 % n][0], track[f][k1 % n][0]
            drift[0] += p1[0] - p0[0]
            drift[1] += p1[2] - p0[2]
    norm = math.hypot(*drift) or 1.0
    fwd = (-drift[0] / norm, -drift[1] / norm)
    for f in feet:
        worst = 0.0
        for a, ln in wins[f]:
            k0, k1 = int(math.ceil(a * n)), int(math.floor((a + ln) * n))
            moved = 0.0
            for k in range(k0, k1):
                i, j = k % n, (k + 1) % n
                dt = secs / n
                # Each measured point's ground-relative speed; the planted one is the slower.
                best = min(math.hypot(q[0] - p[0] + fwd[0] * speed * dt, q[2] - p[2] + fwd[1] * speed * dt) for p, q in zip(track[f][i], track[f][j]))
                moved += best
            worst = max(worst, moved)
        worst /= unit
        out["slide_cm"][f] = round(worst * 100, 1)
        if worst > SLIDE_M:
            out["warnings"].append(f"foot {f} slides {worst * 100:.1f} cm while planted (more than {SLIDE_M * 100:.0f})")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    reports, failed = [], False
    for f in a.files:
        r = check_file(f)
        reports.append(r)
        status = "FAIL" if r["errors"] else "warn" if r["warnings"] else "ok"
        print(f"markers {r['file']}: {status}: {len(r['clips'])} gaits, {len(r['errors'])} errors, {len(r['warnings'])} warnings")
        for c in r["clips"]:
            cs = "FAIL" if c["errors"] else "warn" if c["warnings"] else "ok"
            share = " ".join(f"{k} {v:.0%}" for k, v in c["share"].items())
            slide = " ".join(f"{k} {v}" for k, v in c["slide_cm"].items())
            pair = " ".join(f"{k} {v}" for k, v in (c.get("pair") or {}).items())
            print(f"  {c['clip']:11s} {cs:4s}  down {share}  pair {pair or '-'}  sync {c.get('sync', '-')}  slide cm {slide or '-'}")
            for e in c["errors"]:
                print(f"    ERROR {e}")
            for w in c["warnings"]:
                print(f"    warning: {w}")
        for e in r["errors"]:
            if not any(e.endswith(x) for c in r["clips"] for x in c["errors"]):
                print(f"  ERROR {e}")
        failed |= bool(r["errors"])
    if a.json:
        Path(a.json).write_text(json.dumps(reports, indent=1))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
