#!/usr/bin/env python3
"""Where one piece of a composed person's clothes comes through another, at rest and through clips.

    python3 living/tools/characters/cloth_check.py LINE.json [--styles DIR] [--types DIR]
        [--clips CLIPS.glb] [--clip idle,walk] [--frames 16] [--least 2.0] [--json OUT] [--quiet]
        [--springs] [--spring STIFFNESS,DRAG[,GRAVITY]] [--no-spring-scale]

LINE.json is a person's line (`{"type", "proportions", "styles": {"outfit": [...]}, "belly"}`),
or a `NAME.params.json` whose `person` is one. The person is posed the client's way: the type's
skeleton with the line's proportions (characters.rs `bone_scale`, as person_check.py repeats it),
the belly's bone forward and scaled as the spine is (`--old-belly`: not scaled, as before the
body pass's client half), each piece's `Cloth` mesh skinned to the bones by name with its own bind
matrices, and a clip's rotations on the bones (a clip keys rotations and the hips' place; the
hips' place does not change what lies over what, so it is left at rest).

For every pair of pieces of which one is worn over the other (by their slots and layers, written
in each file: a jersey under a smock under its bands and its apron; trousers under a coat, a
smock and an apron; a jersey tucked into the trousers) it measures, frame by frame, how far the inner piece's vertices
stand outside the outer piece's surface: at each inner vertex, the nearest of the outer piece's
outward-facing vertices within 4 cm, and the distance along that vertex's normal; a
vertex whose nearest is at the outer piece's open edge (a hem, a neck hole), or more than
15 mm to the side of it (what shows in a coat's open front), is past the piece and is not
counted. It prints the
worst of each pair in each clip and fails (exit 1) if anything stands out by more than `--least`
millimetres (default 2). Sleeves are left out: an arm swings through a skirt in any clip that
swings it, and that is the clip's, not the clothes'.

A piece's own bones (a skirt's spring chains) ride the nearest bone above them that the person
has, as the client leaves them where it simulates nothing. `--springs` simulates them instead,
with the client's own step (characters.rs `Springs::simulate`: VRM 0.x's rule, a sixtieth of a
second a step) through each clip from its start, a loop once round first and measured on its
second turn, and also says how far the springs carry the cloth from where it rides at rest.
`--spring STIFFNESS,DRAG[,GRAVITY]` tries other values than the files'. `--no-spring-scale` poses
as a client from before the skirts' change does (a spring bone under a scaled bone without that
scale).

Plain Python and numpy.
"""

import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import clips_compare  # noqa: E402
import person_check  # noqa: E402
from merge_primitives import read_accessor, read_glb  # noqa: E402

BELLY_M = 0.108  # compose.rs: metres the belly's bone stands forward for a belly of 1
ARMS = ("Shoulder", "UpperArm", "LowerArm", "Hand", "Thumb", "Index", "Middle", "Ring", "Little")


def quat(q):
    x, y, z, w = q
    n = (x * x + y * y + z * z + w * w) ** 0.5 or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)], [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)], [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


class Skeleton:
    """The type's bones with a line's proportions; `pose` gives each bone's skinning frame."""

    def __init__(self, path, proportions, belly=0.0, belly_scaled=True):
        j, _ = read_glb(path)
        self.nodes = [n for n in j["nodes"]]
        self.parent = {c: i for i, n in enumerate(self.nodes) for c in n.get("children", [])}
        self.index = {n.get("name"): i for i, n in enumerate(self.nodes) if "mesh" not in n}
        self.rest = {i: np.array(n.get("translation", [0, 0, 0]), float) for i, n in enumerate(self.nodes)}
        self.scale = {i: person_check.bone_scale(n.get("name", ""), proportions) for i, n in enumerate(self.nodes)}
        b = self.index.get("J_Fit_Belly")
        if b is not None and not belly_scaled:
            self.scale[b] = None  # a client from before the body pass: the belly's bone has no scale
        if b is not None:
            self.rest[b] = self.rest[b] + np.array([0.0, 0.0, -belly * BELLY_M])

    def pose(self, rotations):
        """{bone name: 4x4 the bone's own vertices take}, with `rotations` {name: quaternion} on the bones."""
        frame, skin = {}, {}

        def world(i):
            if i in frame:
                return frame[i]
            n = self.nodes[i]
            up = world(self.parent[i]) if i in self.parent else np.eye(4)
            t = self.rest[i]
            ps = self.scale.get(self.parent.get(i))
            if ps and ps[0] == "own":
                t = t * np.array(ps[1])
            loc = np.eye(4)
            loc[:3, 3] = t
            q = rotations.get(n.get("name")) or n.get("rotation")
            if q is not None:
                loc[:3, :3] = quat(q)
            w = up @ loc
            s = self.scale.get(i)
            if s and s[0] == "all":
                w = w @ np.diag([s[1], s[1], s[1], 1.0])
            frame[i] = w
            skin[i] = w @ np.diag(list(s[1]) + [1.0]) if s and s[0] == "own" else w
            return w

        for i in self.index.values():
            world(i)
        # Each bone's own frame, without a scale of its own: what a spring bone hangs in.
        self.frames = {name: frame[i] for name, i in self.index.items()}
        return {name: skin[i] for name, i in self.index.items()}, {name: frame[i][:3, 3] for name, i in self.index.items()}

    def own_scale(self, name):
        """A bone's own scale (x, y, z), 1 where it has none."""
        s = self.scale.get(self.index.get(name))
        return np.array(s[1], float) if s and s[0] == "own" else np.ones(3)


STEP = 1.0 / 60.0  # characters.rs: the springs' fixed step


def arc(a, b):
    """The rotation (3x3) that turns unit vector a onto unit vector b by the shortest way."""
    v, c = np.cross(a, b), float(a @ b)
    if c < -1 + 1e-9:
        o = np.cross(a, [1.0, 0.0, 0.0])
        o = o / np.linalg.norm(o) if np.linalg.norm(o) > 1e-6 else np.array([0.0, 1.0, 0.0])
        return 2 * np.outer(o, o) - np.eye(3)
    k = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + k + k @ k / (1 + c)


class Springs:
    """The spring bones a person's pieces bring (a skirt's chains), simulated as the client
    simulates them: characters.rs `rig_springs` and `Springs::simulate`, VRM 0.x's rule. Verlet
    with drag, a pull toward the rest direction, gravity, a fixed length, and the group's
    spheres; fixed steps of a sixtieth of a second.

    `scaled`: a spring bone under a bone with a scale of its own takes that scale, as the
    client does with the change this needs (characters.rs `shape`); without it only the bone's
    offset is scaled, as the client did before, and the cloth on it keeps the file's size."""

    def __init__(self, paths, scaled=True):
        self.scaled = scaled
        self.joints, self.groups, self.spheres, self.at = [], [], [], {}
        for path in paths:
            j, _ = read_glb(path)
            nodes = j["nodes"]
            up = {c: i for i, n in enumerate(nodes) for c in n.get("children", [])}
            block = ((j.get("extensions") or {}).get("VRM") or {}).get("secondaryAnimation") or {}
            ids = []
            for cg in block.get("colliderGroups", []):
                ids.append([])
                for c in cg["colliders"]:
                    ids[-1].append(len(self.spheres))
                    self.spheres.append((nodes[cg["node"]]["name"], np.array([c["offset"]["x"], c["offset"]["y"], c["offset"]["z"]]), float(c["radius"])))
            for g in block.get("boneGroups", []):
                gi = len(self.groups)
                gd = g.get("gravityDir", {})
                self.groups.append(dict(stiffness=float(g.get("stiffiness", 0)), gravity=np.array([gd.get("x", 0), gd.get("y", -1), gd.get("z", 0)], float) * float(g.get("gravityPower", 0)),
                                        drag=min(max(float(g.get("dragForce", 0)), 0.0), 1.0), radius=float(g.get("hitRadius", 0)), spheres=[k for c in g.get("colliderGroups", []) for k in ids[c]]))
                stack = list(reversed(g["bones"]))
                while stack:
                    i = stack.pop()
                    n = nodes[i]
                    if n["name"] in self.at:
                        continue
                    kids = n.get("children", [])
                    t = np.array(n.get("translation", [0, 0, 0]), float)
                    child = np.array(nodes[kids[0]].get("translation", [0, 0, 0]), float) if kids else None
                    # A leaf's tail lies 7 cm on along its own offset (UniVRM).
                    tail = child if child is not None and np.linalg.norm(child) > 1e-5 else t / max(np.linalg.norm(t), 1e-9) * 0.07
                    self.at[n["name"]] = len(self.joints)
                    self.joints.append(dict(name=n["name"], up=nodes[up[i]]["name"], t=t, r0=quat(n.get("rotation", [0, 0, 0, 1])), axis=tail / np.linalg.norm(tail), len=float(np.linalg.norm(tail)), group=gi, tail=None, prev=None))
                    stack.extend(reversed(kids))
        self.out = {}

    def step(self, sk, steps=1, fresh=False):
        """`steps` fixed steps against the skeleton's pose now (`sk.frames`); each joint's frame goes to `self.out`."""
        centres = []
        for bone, off, r in self.spheres:
            s = sk.own_scale(bone)
            g = sk.frames.get(bone)
            centres.append((None, 0.0) if g is None else ((g @ np.append(off * s, 1.0))[:3], r * (s[0] + s[2]) * 0.5))
        for step in range(max(steps, 1)):
            for j in self.joints:
                if j["up"] in self.at:
                    parent, own = self.out[j["up"]], np.ones(3)
                    t = j["t"]
                else:
                    parent, own = sk.frames[j["up"]], sk.own_scale(j["up"])
                    t = j["t"] * own  # `shape` scales a scaled bone's children's offsets
                ps = np.linalg.norm(parent[:3, :3], axis=0)
                pr = parent[:3, :3] / ps
                sc = max(abs(ps[0]), 1e-6)
                g = self.groups[j["group"]]
                pos = (parent @ np.append(t, 1.0))[:3]
                rest = pr @ j["r0"]
                rest_dir = rest @ j["axis"]
                length = j["len"] * sc
                if fresh and step == 0 or j["tail"] is None:
                    j["tail"] = pos + rest_dir * length
                    j["prev"] = j["tail"].copy()
                if steps > 0:
                    nxt = j["tail"] + (j["tail"] - j["prev"]) * (1.0 - g["drag"]) + rest_dir * (g["stiffness"] * STEP * sc) + g["gravity"] * (STEP * sc)
                    d = nxt - pos
                    nxt = pos + (d / np.linalg.norm(d) if np.linalg.norm(d) > 1e-9 else rest_dir) * length
                    for si in g["spheres"]:
                        c, r = centres[si]
                        if c is None:
                            continue
                        r = r + g["radius"] * sc
                        d = nxt - c
                        if d @ d < r * r:
                            pushed = c + (d / np.linalg.norm(d) if np.linalg.norm(d) > 1e-9 else rest_dir) * r
                            e = pushed - pos
                            nxt = pos + (e / np.linalg.norm(e) if np.linalg.norm(e) > 1e-9 else rest_dir) * length
                    j["prev"], j["tail"] = j["tail"], nxt
                to = j["tail"] - pos
                to = to / np.linalg.norm(to) if np.linalg.norm(to) > 1e-9 else rest_dir
                world = arc(rest_dir / np.linalg.norm(rest_dir), to) @ rest
                local = pr.T @ world
                m = np.eye(4)
                m[:3, :3] = local * (own if self.scaled else np.ones(3))[None, :]
                m[:3, 3] = t
                self.out[j["name"]] = parent @ m
        return self.out


class Piece:
    def __init__(self, path):
        j, binary = read_glb(path)
        self.name = os.path.basename(path)[:-4]
        wear = (j["scenes"][0].get("extras") or {}).get("outfit") or {}
        self.slot, self.layer = wear.get("slot"), wear.get("layer", 0)
        node = next(n for n in j["nodes"] if n.get("name") == "Cloth" and "mesh" in n)
        skin = j["skins"][node.get("skin", 0)]
        self.joints = [j["nodes"][k].get("name") for k in skin["joints"]]
        # Each bone's parent in the piece's own file: a bone only the piece has (a skirt's spring
        # bones) rides the nearest bone above it that the person has, as the client leaves it
        # where no spring is simulated.
        self.up = {c.get("name"): n.get("name") for n in j["nodes"] for c in (j["nodes"][i] for i in n.get("children", []))}
        self.ibm = np.array(read_accessor(j, binary, skin["inverseBindMatrices"])[0]).reshape(-1, 4, 4).transpose(0, 2, 1)
        pos, jt, wt, tris, count = [], [], [], [], 0
        for p in j["meshes"][node["mesh"]]["primitives"]:
            get = lambda a: np.array(read_accessor(j, binary, p["attributes"][a])[0])
            pos.append(get("POSITION").reshape(-1, 3))
            jt.append(get("JOINTS_0").reshape(-1, 4).astype(int))
            wt.append(get("WEIGHTS_0").reshape(-1, 4))
            tris.append(np.array(read_accessor(j, binary, p["indices"])[0]).reshape(-1, 3) + count)
            count += len(pos[-1])
        self.pos, self.jt, self.wt, self.tris = np.concatenate(pos), np.concatenate(jt), np.concatenate(wt), np.concatenate(tris)
        # The piece's open edges (a hem, a neck hole, a cut panel's side) and the vertices next to
        # them: what lies beyond an edge is not under the piece.
        edges = np.sort(np.concatenate([self.tris[:, [0, 1]], self.tris[:, [1, 2]], self.tris[:, [2, 0]]]), axis=1)
        # Vertices are split along UV seams: an edge is open only if no other vertex pair lies on it.
        key = np.round(self.pos * 1e5).astype(np.int64)
        _, vid = np.unique(key, axis=0, return_inverse=True)
        vid = vid.ravel()
        welded = np.sort(vid[edges], axis=1)
        uniq, counts = np.unique(welded, axis=0, return_counts=True)
        open_ids = set(uniq[counts == 1].ravel().tolist())
        rim = np.array([v in open_ids for v in vid])
        near_rim = rim.copy()
        for t in self.tris:
            if rim[t].any():
                near_rim[t] = True
        self.rim = near_rim
        arm = np.array([any(a in n for a in ARMS) for n in self.joints])
        self.on_arm = (self.wt * arm[self.jt]).sum(axis=1) > 0.5
        # The bone that carries most of each vertex, for saying where a fault is.
        self.main = [self.joints[k] for k in self.jt[np.arange(len(self.jt)), self.wt.argmax(axis=1)]]

    def posed(self, mats, springs=None):
        at = {n: k for k, n in enumerate(self.joints)}

        def frame(n):
            if springs is not None and n in springs and n in at:
                return springs[n] @ self.ibm[at[n]]
            # The person's own bone; else the piece's bone as a rigid child of the nearest bone
            # above it that the person has (that bone's frame times its own bind's inverse here).
            while n not in mats and n in self.up and self.up[n] in at:
                n = self.up[n]
            return mats.get(n, np.eye(4)) @ self.ibm[at[n]] if n in at else np.eye(4)

        m = np.array([frame(n) for n in self.joints])
        ph = np.concatenate([self.pos, np.ones((len(self.pos), 1))], axis=1)
        out = np.zeros((len(ph), 3))
        for k in range(4):
            out += self.wt[:, k : k + 1] * np.einsum("nij,nj->ni", m[self.jt[:, k]], ph)[:, :3]
        return out

    def normals(self, p):
        n = np.zeros_like(p)
        f = np.cross(p[self.tris[:, 1]] - p[self.tris[:, 0]], p[self.tris[:, 2]] - p[self.tris[:, 0]])
        for k in range(3):
            np.add.at(n, self.tris[:, k], f)
        return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)


def axis_points(joints):
    """Points along the body's middle (the spine and each leg), to tell an outward face from a lining's."""
    names = [("J_Bip_C_Hips", "J_Bip_C_Spine", "J_Bip_C_Chest", "J_Bip_C_UpperChest", "J_Bip_C_Neck"), ("J_Bip_L_UpperLeg", "J_Bip_L_LowerLeg", "J_Bip_L_Foot"), ("J_Bip_R_UpperLeg", "J_Bip_R_LowerLeg", "J_Bip_R_Foot")]
    pts = []
    for chain in names:
        for a, b in zip(chain, chain[1:]):
            pts += [joints[a] + (joints[b] - joints[a]) * t for t in np.linspace(0, 1, 9)]
    return np.array(pts)


def over(inner, outer):
    """Whether `outer` is worn over `inner` where the two can meet."""
    if inner is outer:
        return False
    if inner.slot == outer.slot:
        return inner.layer < outer.layer
    if inner.slot == "lower":
        # Trousers are under a coat, a smock and an apron. Boots stand on the shin with the
        # trousers tucked in: one bone carries both.
        return outer.slot == "upper" and outer.layer >= 1
    # A jersey (the upper slot's first layer) is tucked into the trousers.
    return inner.slot == "upper" and inner.layer == 0 and outer.slot == "lower"


def through(inner, pi, outer, po, no, axis, reach=0.04, beside=0.015):
    """How far each of the inner piece's vertices stands outside the outer piece (metres; nan where
    the outer piece is not near)."""
    keep = ~outer.on_arm
    if not keep.any() or inner.on_arm.all():
        return np.full(len(pi), np.nan)
    c = axis[np.argmin(((po[keep][:, None, :] - axis[None, :, :]) ** 2).sum(axis=2), axis=1)]
    out_face = (no[keep] * (po[keep] - c)).sum(axis=1) > 0
    # A solid piece (a coat with its lining) has no open edge: its edge is where its outward
    # faces meet the ones that face in. Those vertices and their neighbours count as its rim.
    facing = np.zeros(len(po), bool)
    facing[np.where(keep)[0][out_face]] = True
    turn = facing[outer.tris].any(axis=1) & ~facing[outer.tris].all(axis=1)
    edge = np.zeros(len(po), bool)
    edge[outer.tris[turn].ravel()] = True
    edge[outer.tris[edge[outer.tris].any(axis=1)].ravel()] = True
    q, n, rim = po[keep][out_face], no[keep][out_face], (outer.rim | edge)[keep][out_face]
    if not len(q):
        return np.full(len(pi), np.nan)
    depth = np.full(len(pi), np.nan)
    idx = np.where(~inner.on_arm)[0]
    for s in range(0, len(idx), 400):
        i = idx[s : s + 400]
        d2 = ((pi[i][:, None, :] - q[None, :, :]) ** 2).sum(axis=2)
        k = d2.argmin(axis=1)
        near = (d2[np.arange(len(i)), k] < reach * reach) & ~rim[k]
        out = ((pi[i] - q[k]) * n[k]).sum(axis=1)
        # Under the piece, not beside it: a coat is a solid with no open edge, and what shows in
        # its open front is not through it. The nearest vertex must be nearly straight above.
        near &= d2[np.arange(len(i)), k] - out * out < beside * beside
        depth[i[near]] = out[near]
    return depth


def springs_rest(springs, sk):
    """The spring bones' frames at rest on the skeleton's pose now, leaving the simulation's state alone."""
    keep = [(j["tail"], j["prev"]) for j in springs.joints]
    out_keep = dict(springs.out)
    rest = dict(springs.step(sk, 0, fresh=True))
    for j, (tail, prev) in zip(springs.joints, keep):
        j["tail"], j["prev"] = tail, prev
    springs.out = out_keep
    return rest


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("line")
    ap.add_argument("--styles", default="living/game/assets/lookdev/styles")
    ap.add_argument("--types", default="living/game/assets/lookdev/types")
    ap.add_argument("--clips", default="living/game/assets/lookdev/anim/own-clips.glb")
    ap.add_argument("--clip", default="idle,walk")
    ap.add_argument("--frames", type=int, default=16)
    ap.add_argument("--least", type=float, default=2.0, help="millimetres an inner piece may stand out of an outer one (default 2)")
    ap.add_argument("--json")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--old-belly", action="store_true", help="pose as a client from before the body pass does: `J_Fit_Belly` without the spine's scale")
    ap.add_argument("--springs", action="store_true", help="simulate the pieces' spring bones (a skirt's chains) through each clip as the client does, a sixtieth of a second a step; without it they rest, as on a character the client does not simulate")
    ap.add_argument("--spring", default="", metavar="STIFFNESS,DRAG[,GRAVITY]", help="with --springs: try these values in place of the files' own, to tune them")
    ap.add_argument("--no-spring-scale", action="store_true", help="pose as a client from before the skirts' change does: a spring bone under a scaled bone does not take its scale")
    a = ap.parse_args()
    doc = json.load(open(a.line))
    line = doc.get("person", doc)
    sk = Skeleton(os.path.join(a.types, line["type"] + ".glb"), line.get("proportions") or {}, float(line.get("belly", 0.0)), belly_scaled=not a.old_belly)
    pieces = [Piece(os.path.join(a.styles, "outfit", n + ".glb")) for n in line["styles"]["outfit"]]
    pairs = [(i, o) for i in pieces for o in pieces if over(i, o)]
    library = clips_compare.clips(a.clips)[0] if a.clip and os.path.exists(a.clips) else {}
    springs = Springs([os.path.join(a.styles, "outfit", n + ".glb") for n in line["styles"]["outfit"]], scaled=not a.no_spring_scale)
    if not springs.joints:
        springs = None
    elif a.spring:
        v = [float(x) for x in a.spring.split(",")]
        for g in springs.groups:
            g.update(stiffness=v[0], drag=v[1], gravity=np.array([0.0, -1.0, 0.0]) * (v[2] if len(v) > 2 else 0.0))
    loops = {c["name"]: c.get("kind") == "loop" for c in json.load(open(os.path.join(HERE, "..", "blender", "clips.json")))["clips"]}
    at_time = lambda tracks, t: {node: clips_compare.at(times, values, 4, t) for (node, path), (times, values) in tracks.items() if path == "rotation"}

    def poses():
        """(clip, time, the bones' frames, the bones' places, the spring bones' frames or None), pose by pose."""
        mats, joints = sk.pose({})
        yield "rest", 0.0, mats, joints, (dict(springs.step(sk, 0, fresh=True)) if springs else None)
        for name in [c for c in a.clip.split(",") if c]:
            tracks = library.get(name)
            if tracks is None:
                print(f"cloth_check: no clip {name!r} in {a.clips}")
                continue
            length = max(t[0][-1] for t in tracks.values())
            if springs and a.springs:
                # The clip played from its start a sixtieth of a second a step, the springs
                # following; a loop is played once round first, and measured on its second turn.
                steps = max(int(round(length / STEP)), 1)
                first = steps if loops.get(name) else 0
                want = {first + int(round(f * steps / a.frames)) for f in range(a.frames)}
                for n in range(first + steps):
                    t = (n % steps) * STEP
                    mats, joints = sk.pose(at_time(tracks, t))
                    out = springs.step(sk, 1, fresh=n == 0)
                    if n in want:
                        yield name, t, mats, joints, dict(out)
            else:
                for f in range(a.frames):
                    t = length * f / a.frames
                    mats, joints = sk.pose(at_time(tracks, t))
                    yield name, t, mats, joints, (dict(springs.step(sk, 0, fresh=True)) if springs else None)

    worst, swing, count = {}, {}, 0
    for clip, t, mats, joints, sprung in poses():
        count += 1
        axis = axis_points(joints)
        posed = {p.name: p.posed(mats, sprung) for p in pieces}
        if sprung is not None and a.springs:
            # How far the springs carry the cloth from where it rides unsimulated.
            for p in pieces:
                d = float(np.linalg.norm(posed[p.name] - p.posed(mats, dict(springs_rest(springs, sk))), axis=1).max()) * 1000
                swing[clip] = max(swing.get(clip, 0.0), d)
        normal = {p.name: p.normals(posed[p.name]) for p in pieces}
        for i, o in pairs:
            d = through(i, posed[i.name], o, posed[o.name], normal[o.name], axis)
            if np.all(np.isnan(d)):
                continue
            k = int(np.nanargmax(d))
            key = (i.name, o.name, clip)
            r = worst.setdefault(key, dict(most=-1.0, frames=0, of=0))
            r["of"] += 1
            if d[k] * 1000 > a.least:
                r["frames"] += 1
            if d[k] * 1000 > r["most"]:
                r.update(most=float(d[k] * 1000), at=round(t, 2), bone=i.main[k], out=int(np.nansum(d * 1000 > a.least)))
    bad = 0
    for (i, o, clip), r in sorted(worst.items()):
        fault = r["most"] > a.least
        bad += fault
        if fault or not a.quiet:
            print(f"{i:16s} under {o:16s} {clip:6s} {'THROUGH' if fault else 'clear  '} by {r['most']:6.1f} mm at most (t {r.get('at', 0):.2f} s, on {r.get('bone', '-')}, {r.get('out', 0)} vertices); in {r['frames']} of {r['of']} poses")
    if a.json:
        json.dump({f"{i}|{o}|{clip}": r for (i, o, clip), r in worst.items()}, open(a.json, "w"), indent=1)
    if swing:
        print("cloth_check: springs simulated; the cloth is carried at most " + ", ".join(f"{v:.0f} mm in {c}" for c, v in swing.items()) + " from where it rides at rest")
    print(f"cloth_check: {len(pairs)} pairs of pieces over {count} poses: " + (f"{bad} come through by more than {a.least} mm" if bad else f"none comes through by more than {a.least} mm"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
