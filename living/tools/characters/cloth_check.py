#!/usr/bin/env python3
"""Where one piece of a composed person's clothes comes through another, at rest and through clips.

    python3 living/tools/characters/cloth_check.py LINE.json [--styles DIR] [--types DIR]
        [--clips CLIPS.glb] [--clip idle,walk] [--frames 16] [--least 2.0] [--json OUT] [--quiet] [--chair MM]

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

In `sit_idle`, where a person is seated throughout, it also puts a chair under them (`chair`:
the seat's top at the underside of the seated trousers, its back 2 cm behind them) and says how
far each skirted piece (a smock, an apron, a coat) is below the seat's top and behind the
chair's back; and in `sit_ground`, where a person sits on the ground as the game's townspeople
do, how far each is under the ground (the lowest of the seated trousers and boots). With
`--chair MM` these fail over MM millimetres; without it, they are reported only:
a skirt's back flares behind the thighs standing and turns with them seated, which no fixed
weight mends (docs/CHARACTERS.md, "Sitting").

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
        return {name: skin[i] for name, i in self.index.items()}, {name: frame[i][:3, 3] for name, i in self.index.items()}


class Piece:
    def __init__(self, path):
        j, binary = read_glb(path)
        self.name = os.path.basename(path)[:-4]
        wear = (j["scenes"][0].get("extras") or {}).get("outfit") or {}
        if not wear.get("slot") or "layer" not in wear:
            raise ValueError(f"{path}: missing outfit slot or layer. Finish the style build before measuring.")
        self.slot, self.layer = wear["slot"], wear["layer"]
        node = next(n for n in j["nodes"] if n.get("name") == "Cloth" and "mesh" in n)
        skin = j["skins"][node.get("skin", 0)]
        self.joints = [j["nodes"][k].get("name") for k in skin["joints"]]
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

    def posed(self, mats):
        m = np.array([mats.get(n, np.eye(4)) @ self.ibm[k] for k, n in enumerate(self.joints)])
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


SEATED = ("sit_idle",)  # the clips in which a person is seated on a chair throughout
GROUND = ("sit_ground",)  # and on the ground: what the game's townspeople do (town.rs)
OUTER = ("smock_5", "smock_7", "apron", "coat")  # the pieces with a skirt


def chair(pieces, posed, mats, joints):
    """A chair under a seated person, and what of their skirts is in it: {piece: (millimetres
    below the seat's top, millimetres behind the chair's back, vertices more than 5 mm in
    either)}. No scene has the seat, so it is put where the body says it is: the seat's top at
    the underside of the seated trousers (the lowest of them under the pelvis and the thighs),
    from 4 cm behind the trousers' back to 8 cm short of the knees and 25 cm each side; the
    chair's back upright, 2 cm behind the trousers' back, to 45 cm above the seat."""
    tr = next((p for p in pieces if p.name.startswith("trousers")), None)
    if tr is None:
        return {}
    hips = joints["J_Bip_C_Hips"]
    fwd = -mats["J_Bip_C_Hips"][:3, 2].copy()
    fwd[1] = 0.0
    fwd /= np.linalg.norm(fwd)
    side = np.cross([0.0, 1.0, 0.0], fwd)
    tv = posed[tr.name] - hips
    knee = min(float((joints[f"J_Bip_{s}_LowerLeg"] - hips) @ fwd) for s in "LR")
    along = tv @ fwd
    under = (along > -0.2) & (along < knee - 0.08) & (np.abs(tv @ side) < 0.25)
    if not under.any():
        return {}
    seat = float(tv[under][:, 1].min())
    back = float(along[tv[:, 1] > seat + 0.02].min())
    out = {}
    for p in pieces:
        if not p.name.startswith(OUTER):
            continue
        v = posed[p.name] - hips
        a = v @ fwd
        on = (a > back - 0.04) & (a < knee - 0.08) & (np.abs(v @ side) < 0.25)
        below = seat - v[:, 1]
        behind = (back - 0.02) - a
        up = (v[:, 1] > seat) & (v[:, 1] < seat + 0.45) & (np.abs(v @ side) < 0.25)
        out[p.name] = (
            1000 * below[on].max(initial=0.0),
            1000 * behind[up].max(initial=0.0),
            int((((below > 0.005) & on) | ((behind > 0.005) & up)).sum()),
        )
    return out


def ground(pieces, posed):
    """The ground under a person seated on it, and what of their skirts is under it: {piece:
    (millimetres below the ground, 0.0, vertices more than 5 mm below)}. The ground is where
    the body rests: the lowest of the seated person's trousers and boots."""
    low = [posed[p.name][:, 1].min() for p in pieces if p.name.startswith(("trousers", "boots"))]
    if not low:
        return {}
    floor = float(min(low))
    return {p.name: (max(floor - float(posed[p.name][:, 1].min()), 0.0) * 1000, 0.0, int((posed[p.name][:, 1] < floor - 0.005).sum())) for p in pieces if p.name.startswith(OUTER)}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("line")
    ap.add_argument("--chair", type=float, default=None, metavar="MM", help="fail above MM millimetres of seated contact with the seat top or back in sit_idle, or the floor in sit_ground")
    ap.add_argument("--styles", default="living/game/assets/lookdev/styles")
    ap.add_argument("--types", default="living/game/assets/lookdev/types")
    ap.add_argument("--clips", default="living/game/assets/lookdev/anim/own-clips.glb")
    ap.add_argument("--clip", default="idle,walk")
    ap.add_argument("--frames", type=int, default=16)
    ap.add_argument("--least", type=float, default=2.0, help="millimetres an inner piece may stand out of an outer one (default 2)")
    ap.add_argument("--json")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--old-belly", action="store_true", help="pose as a client from before the body pass does: `J_Fit_Belly` without the spine's scale")
    a = ap.parse_args()
    doc = json.load(open(a.line))
    line = doc.get("person", doc)
    sk = Skeleton(os.path.join(a.types, line["type"] + ".glb"), line.get("proportions") or {}, float(line.get("belly", 0.0)), belly_scaled=not a.old_belly)
    pieces = [Piece(os.path.join(a.styles, "outfit", n + ".glb")) for n in line["styles"]["outfit"]]
    pairs = [(i, o) for i in pieces for o in pieces if over(i, o)]
    library = clips_compare.clips(a.clips)[0] if a.clip and os.path.exists(a.clips) else {}
    poses = [("rest", 0.0, {})]
    for name in [c for c in a.clip.split(",") if c]:
        tracks = library.get(name)
        if tracks is None:
            ap.error(f"no clip {name!r} in {a.clips}")
        length = max(t[0][-1] for t in tracks.values())
        for f in range(a.frames):
            t = length * f / a.frames
            poses.append((name, t, {node: clips_compare.at(times, values, 4, t) for (node, path), (times, values) in tracks.items() if path == "rotation"}))
    worst, seats = {}, {}
    for clip, t, rot in poses:
        mats, joints = sk.pose(rot)
        axis = axis_points(joints)
        posed = {p.name: p.posed(mats) for p in pieces}
        if clip in SEATED or clip in GROUND:
            for name, (below, behind, n) in (chair(pieces, posed, mats, joints) if clip in SEATED else ground(pieces, posed)).items():
                r = seats.setdefault((name, clip), dict(below=0.0, behind=0.0, vertices=0))
                r.update(below=max(r["below"], below), behind=max(r["behind"], behind), vertices=max(r["vertices"], n))
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
    cloth_bad = bad
    for (name, clip), r in sorted(seats.items()):
        fault = a.chair is not None and max(r["below"], r["behind"]) > a.chair
        bad += fault
        if fault or not a.quiet:
            if clip in SEATED:
                print(f"{name:16s} {clip}: seat top  {r['below']:6.1f} mm below")
                print(f"{name:16s} {clip}: seat back {r['behind']:6.1f} mm behind")
            else:
                print(f"{name:16s} {clip}: ground    {r['below']:6.1f} mm below")
            print(f"  {r['vertices']} vertices beyond 5 mm at most in one pose" + ("; exceeds contact limit" if fault else ""))
    if a.json:
        json.dump(dict({f"{i}|{o}|{clip}": r for (i, o, clip), r in worst.items()}, **{f"{name}|{'chair' if clip in SEATED else 'ground'}|{clip}": dict(most=max(r["below"], r["behind"]), **r) for (name, clip), r in seats.items()}), open(a.json, "w"), indent=1)
    print(f"cloth_check: {len(pairs)} pairs of pieces over {len(poses)} poses: " + (f"{cloth_bad} pair/clip results come through by more than {a.least} mm" if cloth_bad else f"none comes through by more than {a.least} mm"))
    if bad > cloth_bad:
        print(f"cloth_check: {bad - cloth_bad} seat or ground results exceed {a.chair} mm")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
