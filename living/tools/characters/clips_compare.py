#!/usr/bin/env python3
"""Whether two character files' clips are the same motion: for each clip both carry, the largest
difference between their keyed rotations (degrees) and translations (metres), bone by bone,
compared at the same share of each clip's length.

    python3 living/tools/characters/clips_compare.py A.glb B.glb [--top 5]

animate.py bakes the clip library onto every person, so 64 people carry 64 copies. If the copies
agree, one could serve all (docs/CHARACTERS.md, "Crowd cost"). Rotations can be shared when they
agree; the hips' translation scales with the legs and would be scaled by the client, as it
already is for recipes' proportions (characters.rs `hips`). The last line gives the bytes of
clip data in each file. Plain Python.
"""

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from merge_primitives import read_accessor, read_glb  # noqa: E402


def clips(path):
    j, binary = read_glb(path)
    out, size, seen = {}, 0, set()
    for an in j.get("animations", []):
        tracks = {}
        for ch in an["channels"]:
            s = an["samplers"][ch["sampler"]]
            node = j["nodes"][ch["target"]["node"]].get("name", "?")
            t, _ = read_accessor(j, binary, s["input"])
            v, _ = read_accessor(j, binary, s["output"])
            tracks[(node, ch["target"]["path"])] = (list(t), list(v))
            for acc in (s["input"], s["output"]):
                if acc not in seen:
                    seen.add(acc)
                    a = j["accessors"][acc]
                    size += a["count"] * 4 * dict(SCALAR=1, VEC3=3, VEC4=4)[a["type"]]
        out[an.get("name", "?")] = tracks
    return out, size


def at(times, values, n, t):
    """A track's value at time t (linear between keys)."""
    if t <= times[0]:
        return values[:n]
    for k in range(1, len(times)):
        if t <= times[k]:
            f = (t - times[k - 1]) / max(times[k] - times[k - 1], 1e-9)
            p, q = values[n * (k - 1) : n * k], values[n * k : n * k + n]
            if n == 4 and sum(x * y for x, y in zip(p, q)) < 0:
                q = [-y for y in q]
            return [x + (y - x) * f for x, y in zip(p, q)]
    return values[-n:]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--top", type=int, default=5)
    a = ap.parse_args()
    (ca, sa), (cb, sb) = clips(a.a), clips(a.b)
    for name in sorted(set(ca) & set(cb)):
        ta, tb = ca[name], cb[name]
        rot, tr = [], []
        longest = (0.0, 0.0)
        for key in sorted(set(ta) & set(tb)):
            (xa, va), (xb, vb) = ta[key], tb[key]
            n = 4 if key[1] == "rotation" else 3
            longest = max(longest, (xa[-1], xb[-1]))
            # Both tracks sampled at the same share of their own length: animate.py scales a
            # locomotion clip's time by the figure's height, so lengths differ a little.
            worst = 0.0
            for k in range(41):
                p, q = at(xa, va, n, xa[-1] * k / 40), at(xb, vb, n, xb[-1] * k / 40)
                if key[1] == "rotation":
                    d = abs(sum(x * y for x, y in zip(p, q))) / (math.sqrt(sum(x * x for x in p) * sum(y * y for y in q)) or 1.0)
                    worst = max(worst, math.degrees(2 * math.acos(min(d, 1.0))))
                elif key[1] == "translation":
                    worst = max(worst, math.dist(p, q))
            if key[1] in ("rotation", "translation"):
                (rot if key[1] == "rotation" else tr).append((worst, key[0]))
        rot.sort(reverse=True)
        tr.sort(reverse=True)
        only = len(set(ta) ^ set(tb))
        print(f"{name}: lengths {longest[0]:.2f} s and {longest[1]:.2f} s; {len(rot)} rotation tracks, worst {rot[0][0]:.2f}° ({rot[0][1]}); " + ", ".join(f"{n} {d:.2f}°" for d, n in rot[1 : a.top]) +
              (f"; translation worst {tr[0][0] * 100:.1f} cm ({tr[0][1]})" if tr else "") + (f"; {only} tracks in one file only" if only else ""))
    print(f"clip data: {sa / 1e6:.2f} MB in {os.path.basename(a.a)} ({len(ca)} clips), {sb / 1e6:.2f} MB in {os.path.basename(a.b)} ({len(cb)} clips)")


if __name__ == "__main__":
    main()
