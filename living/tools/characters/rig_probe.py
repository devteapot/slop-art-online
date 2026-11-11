#!/usr/bin/env python3
"""Identity bones on an existing character file, to prove the mechanism before any mesh is rebuilt
(docs/CHARACTERS.md, "The rig"): bones under the head that no clip keys, whose local transform
reshapes the face while the clips play.

    python3 living/tools/characters/rig_probe.py IN.glb OUT.glb [--pose] [--list]

IN is a generated person with clips (lookdev/anim/own-<name>.glb). OUT gets five probe bones as
children of `J_Bip_C_Head`, each with a soft weight field on the face's and the hair's vertices:

    J_Id_Cranium   everything above the brows (skin and hair)     --pose: wider, deeper, taller
    J_Id_Jaw       the lower face below the mouth's corners       --pose: narrower
    J_Id_Chin      round the chin's point (a child of the jaw)    --pose: longer, forward
    J_Id_Orbit_L   round the left eye, with the eye's parts       --pose: larger, further out
    J_Id_Orbit_R   the same on the right

Without --pose the bones sit at rest and the file must look exactly as IN does. With --pose their
node transforms differ from their bind pose, which is what the client would write once when it
spawns a person. The clips key only `J_Bip_*` rotations and the hips' translation (--list prints
what a file's clips key), so the pose must hold through every clip. Photograph both through the
game (living/tools/view_assets.sh) to see it.

The weight fields here are simple distances on a mesh that was not built for bones: enough to
show the mechanism, not how a type's mesh will be weighted (that is the cage's job).
Plain Python, no dependencies.
"""

import argparse
import collections
import math
import os
import sys
from array import array

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from merge_primitives import append_accessor, read_accessor, read_glb, write_glb  # noqa: E402

FLOAT, UBYTE, USHORT, ARRAY_BUFFER = 5126, 5121, 5123, 34962


def smooth(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def world_positions(j):
    """Each node's rest position in the file's space (rest rotations are identity)."""
    parent = {}
    for i, n in enumerate(j["nodes"]):
        for c in n.get("children", []):
            parent[c] = i
    out = {}

    def at(i):
        if i not in out:
            t = j["nodes"][i].get("translation", [0, 0, 0])
            p = at(parent[i]) if i in parent else (0.0, 0.0, 0.0)
            out[i] = tuple(a + b for a, b in zip(p, t))
        return out[i]

    for i in range(len(j["nodes"])):
        at(i)
    return out


def keyed(j):
    """Bone name -> the paths (rotation, translation, scale) any clip keys on it."""
    out = collections.defaultdict(set)
    for an in j.get("animations", []):
        for ch in an["channels"]:
            out[j["nodes"][ch["target"]["node"]].get("name", "?")].add(ch["target"]["path"])
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("inp")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--pose", action="store_true", help="give the probe bones a pose (a different person on the same mesh)")
    ap.add_argument("--list", action="store_true", help="print which bones the file's clips key, and stop")
    a = ap.parse_args()
    j, binary = read_glb(a.inp)
    nodes = j["nodes"]
    skin = j["skins"][0]
    names = [nodes[i].get("name", "") for i in skin["joints"]]
    k = keyed(j)
    by_paths = collections.Counter(tuple(sorted(v)) for v in k.values())
    print(f"{a.inp}: {len(j.get('animations', []))} clips key {len(k)} bones: " + ", ".join(f"{n} by {' and '.join(p)}" for p, n in by_paths.items()))
    print(f"  bones in the skin that no clip keys ({sum(n not in k for n in names)} of {len(names)}): " + ", ".join(n for n in names if n not in k))
    if a.list or not a.out:
        return
    assert len(j["skins"]) == 1, "one skin a file is expected"
    head = next(i for i, n in enumerate(nodes) if n.get("name") == "J_Bip_C_Head")
    wp = world_positions(j)
    mats = j["materials"]
    prims = [(m, p) for m in j["meshes"] for p in m["primitives"] if not m.get("name", "").startswith("Far")]
    face = [(m, p) for m, p in prims if m.get("name") == "Face"]
    skin_prim = next(p for m, p in face if mats[p["material"]]["name"].endswith("Face_00_SKIN"))
    pos, _ = read_accessor(j, binary, skin_prim["attributes"]["POSITION"])
    pts = [pos[i : i + 3] for i in range(0, len(pos), 3)]
    # The file faces -Z with Y up. Landmarks from the face's own skin.
    front = [p for p in pts if abs(p[0]) < 0.004]
    chin = min(front, key=lambda p: p[1])
    top = max(p[1] for p in pts)
    eye_bones = {s: wp[next(i for i, n in enumerate(nodes) if n.get("name") == f"J_Adj_{s}_FaceEye")] for s in "LR"}
    eye_y = eye_bones["L"][1]
    brow_y = eye_y + 0.028
    mouth_y = chin[1] + 0.045
    print(f"  landmarks (file space, m): chin y {chin[1]:.3f}, eyes y {eye_y:.3f}, top of the skin y {top:.3f}")

    def eye_centre(s):
        # On the skin in front of the eye's bone.
        b = eye_bones[s]
        near = min(pts, key=lambda p: (p[0] - b[0]) ** 2 + (p[1] - b[1]) ** 2 + (0 if p[2] < b[2] else 1))
        return (b[0], b[1], near[2])

    probes = [
        dict(name="J_Id_Cranium", parent=head, pivot=(0.0, brow_y, wp[head][2]), meshes=("Face", "Hair"), weight=lambda p: smooth((p[1] - brow_y + 0.012) / 0.03),
             scale=(1.10, 1.05, 1.08), move=(0, 0, 0)),
        dict(name="J_Id_Jaw", parent=head, pivot=(0.0, mouth_y + 0.02, chin[2] + 0.06), meshes=("Face",), weight=lambda p: smooth((mouth_y + 0.012 - p[1]) / 0.03) * smooth((chin[2] + 0.09 - p[2]) / 0.04),
             scale=(0.86, 1.0, 1.0), move=(0, 0, 0)),
        dict(name="J_Id_Chin", parent="J_Id_Jaw", pivot=tuple(chin), meshes=("Face",), weight=lambda p: smooth(1 - math.dist(p, chin) / 0.045), scale=(1, 1, 1), move=(0, -0.012, -0.005)),
    ]
    for s in "LR":
        c = eye_centre(s)
        sign = 1 if c[0] > 0 else -1
        probes.append(dict(name=f"J_Id_Orbit_{s}", parent=head, pivot=c, meshes=("Face",), weight=lambda p, c=c: smooth(1.25 - math.dist((p[0], p[1]), (c[0], c[1])) / 0.030) * (abs(p[2] - c[2]) < 0.05) * (p[0] * c[0] > 0),
                           scale=(1.14, 1.14, 1.0), move=(0.004 * sign, -0.002, 0)))
    index = {}
    ibm, _ = read_accessor(j, binary, skin["inverseBindMatrices"])
    ibm = array("f", ibm)
    for pr in probes:
        parent = pr["parent"] if isinstance(pr["parent"], int) else index[pr["parent"]]
        ppos = wp[parent]
        rest = [c - q for c, q in zip(pr["pivot"], ppos)]
        node = dict(name=pr["name"], translation=[r + m for r, m in zip(rest, pr["move"])] if a.pose else rest)
        if a.pose and pr["scale"] != (1, 1, 1):
            node["scale"] = list(pr["scale"])
        nodes.append(node)
        ni = len(nodes) - 1
        nodes[parent].setdefault("children", []).append(ni)
        wp[ni] = tuple(pr["pivot"])
        index[pr["name"]] = ni
        skin["joints"].append(ni)
        pr["joint"] = len(skin["joints"]) - 1
        px, py, pz = pr["pivot"]
        ibm += array("f", [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -px, -py, -pz, 1])
    skin["inverseBindMatrices"] = append_accessor(j, binary, ibm, FLOAT, "MAT4", False, None)
    # The eye's bones follow their orbit, so the iris moves with the socket.
    for s in "LR":
        eye = next(i for i, n in enumerate(nodes) if n.get("name") == f"J_Adj_{s}_FaceEye")
        orbit = index[f"J_Id_Orbit_{s}"]
        nodes[head]["children"].remove(eye)
        nodes[orbit].setdefault("children", []).append(eye)
        # Its place in the orbit's frame at rest; the orbit's pose then carries it.
        nodes[eye]["translation"] = [e - o for e, o in zip(eye_bones[s], wp[orbit])]
    eye_joint = {names.index(f"J_Adj_{s}_FaceEye"): s for s in "LR"}
    done = {}
    moved = collections.Counter()
    for m, p in prims:
        at = p["attributes"]
        key = (at["POSITION"], at["JOINTS_0"], at["WEIGHTS_0"])
        if key in done:
            at["JOINTS_0"], at["WEIGHTS_0"] = done[key]
            continue
        pos, _ = read_accessor(j, binary, at["POSITION"])
        jt, (jct, _, _) = read_accessor(j, binary, at["JOINTS_0"])
        wt, _ = read_accessor(j, binary, at["WEIGHTS_0"])
        jt, wt = list(jt), list(wt)
        for v in range(len(pos) // 3):
            pt = pos[3 * v : 3 * v + 3]
            for pr in probes:
                if m.get("name") not in pr["meshes"]:
                    continue
                f = pr["weight"](pt)
                # A vertex already on an eye's bone (the iris) keeps to it: the bone itself follows the orbit.
                if any(jt[4 * v + q] in eye_joint and wt[4 * v + q] > 0.5 for q in range(4)):
                    f = 0.0
                if f < 0.004:
                    continue
                # The probe takes its share; what was there keeps the rest, in the three largest slots.
                slots = sorted(range(4), key=lambda q: -wt[4 * v + q])[:3]
                keep = [(jt[4 * v + q], wt[4 * v + q] * (1 - f)) for q in slots]
                total = sum(w for _, w in keep) + f
                new = keep + [(pr["joint"], f)]
                for q, (bone, w) in enumerate(new):
                    jt[4 * v + q], wt[4 * v + q] = bone, w / total
                moved[pr["name"]] += 1
        ja = append_accessor(j, binary, array("H", jt), USHORT, "VEC4", False, ARRAY_BUFFER)
        wa = append_accessor(j, binary, array("f", wt), FLOAT, "VEC4", False, ARRAY_BUFFER)
        done[key] = (ja, wa)
        at["JOINTS_0"], at["WEIGHTS_0"] = ja, wa
    write_glb(a.out, j, binary)
    print(f"  wrote {a.out}: {len(skin['joints'])} joints (Bevy's limit is 256 a skin), probe bones " + ", ".join(f"{n} on {c} vertices" for n, c in moved.items()) + ("; posed" if a.pose else "; at rest"))


if __name__ == "__main__":
    main()
