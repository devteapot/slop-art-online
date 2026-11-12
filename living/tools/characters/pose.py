#!/usr/bin/env python3
"""Pose bones in a character file, to photograph a turn or a nod.

    python3 living/tools/characters/pose.py IN.glb OUT.glb --turn DEG --nod DEG [--tilt DEG] [--share 0.4]

Writes OUT with `J_Bip_C_Neck` and `J_Bip_C_Head` turned in the file's node rotations: the neck
takes `--share` of each angle and the head the rest, each about its own joint. Turn is about
the up axis (positive to the character's left), nod about the side axis (positive down), tilt
about the forward axis (positive toward the character's left shoulder). Nothing else changes:
a file with clips plays them over this, so pose a file without clips (a composed person, a
type) and show it as a plain file.
"""
import argparse
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from merge_primitives import read_glb, write_glb  # noqa: E402


def qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return np.array([aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx, aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz])


def qinv(a):
    return np.array([-a[0], -a[1], -a[2], a[3]])


def axis(v, deg):
    h = math.radians(deg) / 2
    return np.array([v[0] * math.sin(h), v[1] * math.sin(h), v[2] * math.sin(h), math.cos(h)])


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--turn", type=float, default=0.0)
    ap.add_argument("--nod", type=float, default=0.0)
    ap.add_argument("--tilt", type=float, default=0.0)
    ap.add_argument("--share", type=float, default=0.4, help="the neck's share of each angle")
    a = ap.parse_args()
    j, binary = read_glb(a.inp)
    nodes = j["nodes"]
    parent = {c: i for i, n in enumerate(nodes) for c in n.get("children", [])}
    rot = lambda i: np.array(nodes[i].get("rotation", [0, 0, 0, 1]), float)

    def world(i):
        """A node's rest rotation in the file's frame."""
        q = rot(i)
        while i in parent:
            i = parent[i]
            q = qmul(rot(i), q)
        return q

    # In the file's frame (Y up), as the game's photographs show them: a turn to the character's
    # left is about -Y, a nod down about -X, a tilt to the left shoulder about -Z.
    for name, k in (("J_Bip_C_Neck", a.share), ("J_Bip_C_Head", 1.0 - a.share)):
        i = next(i for i, n in enumerate(nodes) if n.get("name") == name)
        r = qmul(axis((0, -1, 0), a.turn * k), qmul(axis((-1, 0, 0), a.nod * k), axis((0, 0, -1), a.tilt * k)))
        p = world(parent[i]) if i in parent else np.array([0, 0, 0, 1.0])
        q = qmul(qmul(qmul(qinv(p), r), p), rot(i))
        nodes[i]["rotation"] = [float(x) for x in q / np.linalg.norm(q)]
    write_glb(a.out, j, binary)
    print(f"pose: {a.out}: turn {a.turn:g}, nod {a.nod:g}, tilt {a.tilt:g} degrees; the neck takes {a.share:g}")


if __name__ == "__main__":
    main()
