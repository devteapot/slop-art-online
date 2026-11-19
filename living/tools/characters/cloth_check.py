#!/usr/bin/env python3
"""Where one piece of a composed person's clothes comes through another, at rest and through clips.

    python3 living/tools/characters/cloth_check.py LINE.json [--styles DIR] [--types DIR]
        [--clips CLIPS.glb] [--clip idle,walk] [--frames 16] [--least 2.0] [--json OUT] [--quiet] [--chair MM]
        [--springs] [--spring STIFFNESS,DRAG[,GRAVITY]] [--no-spring-scale] [--terrain] [--seat-contact]
        [--compare-client JOINTS.jsonl --client-root-y METRES]

LINE.json is a person's line (`{"type", "height", "proportions", "styles": {"outfit": [...]}, "belly"}`),
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


A piece's own bones (a skirt's spring chains) ride the nearest bone above them that the person
has, as the client leaves them where it simulates nothing. `--springs` simulates them instead,
with the client's own step (characters.rs `Springs::simulate`: VRM 0.x's rule, a sixtieth of a
second a step) through each clip from its start, a loop once round first and measured on its
second turn, and also says how far the springs carry the cloth from where it rides at rest.
`--spring STIFFNESS,DRAG[,GRAVITY]` tries other values than the files'. `--no-spring-scale` poses
as a client from before the skirts' change does (a spring bone under a scaled bone without that
scale).

`--terrain` uses the client's pre-shape fitted bounds and scales the ground clips' hips
translation by `hips_k` (`stand_up_ground` plays at 1.6×), their height blended toward 1 as
the clip's hips come down to the seat, as the client does since sit-hips (`--ground-hips`:
`legs` as before, `contact` by the cloth contact's clip-time weight; `--ground-hips-band` tries
another band). It reports garment penetration against the flat floor in model-space
millimetres; `--heights OUT.csv` writes each pose's pelvis and lowest boots, trousers and
skirted piece above it in world millimetres. `--seat-contact` implies `--springs` and
applies the client's weighted ground plane to the cloth spring groups (`Skirt`, `Coat`).

`--compare-client` compares one asset-view joint dump row on a ground clip at an explicit time
(e.g. `LIVING_GAME_VIEW_SHOTS=sit_ground@0.5`). Supply the root's world Y in metres separately,
since the dump is root-relative. In a debug build, break at view.rs:657 in `write_joints` and
read `at.y` (on the flat checker it is the fitted `y_off`, which the tool prints as `root`). The tool
exits 1 if the root, the hips or either foot joint differs by more than 1 mm.

Plain Python and numpy.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import clips_compare  # noqa: E402
import compose  # noqa: E402
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

    def place_hips(self, t=None):
        """The hips' place (file units), as a clip keys it; None puts them back at rest."""
        i = self.index["J_Bip_C_Hips"]
        if not hasattr(self, "hips0"):
            self.hips0 = self.rest[i].copy()
        self.rest[i] = self.hips0.copy() if t is None else np.array(t, float)

    def own_scale(self, name):
        """A bone's own scale (x, y, z), 1 where it has none."""
        s = self.scale.get(self.index.get(name))
        return np.array(s[1], float) if s and s[0] == "own" else np.ones(3)


def vertical_bounds(type_path, styles, line):
    """The composed scene's bounds when first fitted, in model units."""
    model, binary = read_glb(type_path)
    scene = model["scenes"][model.get("scene", 0)]
    nodes = model["nodes"]
    parent = {c: i for i, n in enumerate(nodes) for c in n.get("children", [])}
    by_name = {n.get("name"): i for i, n in enumerate(nodes)}
    if line.get("identity"):
        compose.compose(model, line["identity"])
    belly = by_name.get("J_Fit_Belly")
    if belly is not None:
        nodes[belly]["translation"] = np.array(nodes[belly].get("translation", [0, 0, 0])) + [0, 0, -line.get("belly", 0.0) * BELLY_M]

    frames = {}

    def world(i):
        if i not in frames:
            n = nodes[i]
            local = np.eye(4)
            if "matrix" in n:
                local = np.array(n["matrix"]).reshape(4, 4).T
            else:
                local[:3, :3] = quat(n.get("rotation", [0, 0, 0, 1])) * n.get("scale", [1, 1, 1])
                local[:3, 3] = n.get("translation", [0, 0, 0])
            frames[i] = world(parent[i]) @ local if i in parent else local
        return frames[i]

    def inverse_binds(doc, blob, skin):
        return np.array(read_accessor(doc, blob, skin["inverseBindMatrices"])[0]).reshape(-1, 4, 4).transpose(0, 2, 1)

    # compose.rs:426–440, 543–573: styles bind in the type's rest frame, with hair_fit
    # on hair and headwear. Style-only joints inherit the deformation of their ancestor.
    skin = model["skins"][0]
    delta = {nodes[i]["name"]: world(i) @ ibm for i, ibm in zip(skin["joints"], inverse_binds(model, binary, skin))}
    hair_fit = np.array(scene.get("extras", {}).get("hair_fit", {}).get("matrix", np.eye(4).ravel())).reshape(4, 4).T

    def mesh_bounds(doc, blob, node, rigid, joints):
        for primitive in doc["meshes"][node["mesh"]]["primitives"]:
            attrs = primitive["attributes"]
            accessor = doc["accessors"][attrs["POSITION"]]
            if joints is None:
                boxes = [(accessor["min"], accessor["max"], rigid)]
            else:
                # Bevy 0.20.1 skinned_mesh_bounds: union of each joint's transformed
                # box of influenced vertices, including vertices with a partial weight.
                vertices = np.array(read_accessor(doc, blob, attrs["POSITION"])[0]).reshape(-1, 3)
                indices = np.array(read_accessor(doc, blob, attrs["JOINTS_0"])[0]).reshape(-1, 4)
                weights = np.array(read_accessor(doc, blob, attrs["WEIGHTS_0"])[0]).reshape(-1, 4)
                boxes = []
                for j in np.unique(indices[weights > 0]):
                    points = vertices[np.any((indices == j) & (weights > 0), axis=1)]
                    boxes.append((points.min(axis=0), points.max(axis=0), joints[j]))
            # lookdev.rs:656–671 takes the Y extrema of the boxes in root space.
            for lo, hi, matrix in boxes:
                y = matrix[1, :3]
                yield np.minimum(lo * y, hi * y).sum() + matrix[1, 3], np.maximum(lo * y, hi * y).sum() + matrix[1, 3]

    bounds = []
    pending = list(scene["nodes"])
    while pending:
        i = pending.pop()
        n = nodes[i]
        pending.extend(n.get("children", []))
        if "mesh" not in n:
            continue
        joints = None
        if "skin" in n:
            skin = model["skins"][n["skin"]]
            joints = [world(j) @ ibm for j, ibm in zip(skin["joints"], inverse_binds(model, binary, skin))]
        bounds.extend(mesh_bounds(model, binary, n, world(i), joints))

    wear = line["styles"]
    files = [(Path(styles) / "outfit" / f"{name}.glb", name in ("cap", "kerchief")) for name in wear["outfit"]]
    files.extend((Path(styles) / "overlay" / line["type"] / f"{name}.glb", False) for name in wear.get("overlays", []))
    if wear.get("hair"):
        files.append((Path(styles) / "hair" / f"{wear['hair']}.glb", True))
    for path, fitted in files:
        if not path.exists():  # compose::prepare skips absent styles
            continue
        doc, blob = read_glb(path)
        style_nodes = doc["nodes"]
        up = {c: i for i, n in enumerate(style_nodes) for c in n.get("children", [])}
        fit = hair_fit if fitted else np.eye(4)
        for n in style_nodes:
            if "mesh" not in n or "skin" not in n:
                continue
            joints = []
            for j in doc["skins"][n["skin"]]["joints"]:
                while style_nodes[j].get("name") not in delta and j in up:
                    j = up[j]
                joints.append(delta.get(style_nodes[j].get("name"), np.eye(4)) @ fit)
            bounds.extend(mesh_bounds(doc, blob, n, None, joints))
    return min(lo for lo, _ in bounds), max(hi for _, hi in bounds)


def terrain_fit(sk, bounds, line):
    """Return the model-space floor, final root scale and offset, and keyed hips multiplier."""
    lo, hi = bounds
    # lookdev.rs:676–691 stores the initial vertical span and the fitted base offset.
    span = hi - lo
    if lo < -0.05 * max(span, 0.01) and hi > 0.0:
        lo = 0.0
    top0 = lo + span

    # characters.rs:879–908 recovers the base and span, then sizes the shaped leg and spine.
    def rest(name):
        return sk.rest[sk.index[name]][1]

    hips = "J_Bip_C_Hips"
    upper, lower, foot = ("J_Bip_L_" + name for name in ("UpperLeg", "LowerLeg", "Foot"))
    hips0 = rest(hips)
    foot0 = hips0 + rest(upper) + rest(lower) + rest(foot)
    drop = sum(sk.own_scale(parent)[1] * rest(child) for parent, child in zip((hips, upper, lower), (upper, lower, foot)))
    proportions = line.get("proportions") or {}
    hips_y = lo + (foot0 - lo) * proportions.get("feet", 1.0) - drop
    hips_k = hips_y / hips0 if abs(hips0) > 1e-4 else 1.0
    spine = ["J_Bip_C_" + name for name in ("Spine", "Chest", "UpperChest", "Neck", "Head")]
    head0 = hips0 + sum(rest(b) for b in spine)
    head = hips_y + sum(sk.own_scale(parent)[1] * rest(child) for parent, child in zip([hips] + spine, spine))
    top = head + (top0 - head0) * proportions.get("head", 1.0)
    scale = line["height"] / max(top - lo, 0.01)
    # live.rs:934–936, 1132–1136: root Y is the terrain at the drawn body plus fit.y_off.
    return lo, scale, -lo * scale, hips_k


STEP = 1.0 / 60.0  # characters.rs: the springs' fixed step
CLOTH_GROUPS = ("skirt", "coat")  # characters.rs `CLOTH_GROUPS`: the spring groups a seat contact applies to
SEAT_SINK = 0.25  # characters.rs: how far below the ground a contact at weight 0 lies
SEAT_DOWN_S, SEAT_UP_S, SEAT_RAMP_S = 1.2, 1.3, 0.2  # anim.rs: the ground seat's contact frames and ramp
SEAT_RATE = {"sit_ground_down": 1.0, "sit_ground": 1.0, "stand_up_ground": 1.6}  # the rates the client plays them at (live.rs STAND_UP)


def seat_of(clip, t, rate):
    """anim.rs `seat_of`: how far a ground seat's clip at time t has the body down (0-1), None for another clip."""
    ramp = SEAT_RAMP_S * max(rate, 0.01)
    smooth = lambda x: min(max(x, 0.0), 1.0) ** 2 * (3 - 2 * min(max(x, 0.0), 1.0))
    if clip == "sit_ground_down":
        return smooth((t - (SEAT_DOWN_S - ramp)) / ramp)
    if clip == "sit_ground":
        return 1.0
    if clip == "stand_up_ground":
        return 1.0 - smooth((t - SEAT_UP_S) / ramp)
    return None


GROUND_HIPS_BAND = (0.17, 0.45)  # anim.rs `GROUND_HIPS`: the hips' heights (fractions of their rest) between which a ground seat's clip takes hips_k from 1 back to the legs'


def ground_hips_k(mode, clip, t, h, hips_k, hips0, band=GROUND_HIPS_BAND):
    """The multiplier on the hips' height in a ground seat's clip (characters.rs `hips`).

    `legs`: hips_k throughout, as before sit-hips. `contact`: hips_k blended to 1 by the cloth
    contact's clip-time weight (`seat_of`). `height`: blended to 1 by the clip's own hips
    height h (file units) against their rest height hips0: all the way at or below band[0] of
    it, not at all at or above band[1] (anim.rs `ground_hips`, the client's since sit-hips)."""
    if mode == "legs" or clip not in SEAT_RATE:
        return hips_k
    if mode == "contact":
        w = seat_of(clip, t, SEAT_RATE[clip])
    else:
        x = min(max((band[1] * hips0 - h) / max((band[1] - band[0]) * hips0, 1e-6), 0.0), 1.0)
        w = x * x * (3 - 2 * x)
    return hips_k + (1.0 - hips_k) * w


def keep_above(ground, pos, nxt, length, r):
    """characters.rs `Contact::keep` on a level ground at height `ground`: the tail kept r above
    it, as near nxt as the chain's length lets it; a chain whose root is under it lies flat at most."""
    if nxt[1] - ground >= r:
        return nxt
    d = nxt - pos
    u = d / np.linalg.norm(d) if np.linalg.norm(d) > 1e-9 else np.array([0.0, -1.0, 0.0])
    h = pos[1] - ground - r
    least = min(max(-h / max(length, 1e-6), -1.0), 0.0)
    if u[1] >= least:
        return nxt
    side = u - np.array([0.0, u[1], 0.0])
    side = side / np.linalg.norm(side) if np.linalg.norm(side) > 1e-9 else np.array([1.0, 0.0, 0.0])
    return pos + (np.array([0.0, least, 0.0]) + side * max(1 - least * least, 0.0) ** 0.5) * length


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
                self.groups.append(dict(cloth=str(g.get("comment", "")).strip().lower() in CLOTH_GROUPS, stiffness=float(g.get("stiffiness", 0)), gravity=np.array([gd.get("x", 0), gd.get("y", -1), gd.get("z", 0)], float) * float(g.get("gravityPower", 0)),
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

    def step(self, sk, steps=1, fresh=False, contact=None):
        """`steps` fixed steps against the skeleton's pose now (`sk.frames`); each joint's frame goes to `self.out`.
        `contact`: weighted ground plane height in model units, or None."""
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
                    if contact is not None and g["cloth"]:
                        nxt = keep_above(contact, pos, nxt, length, g["radius"] * sc)
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
        if not wear.get("slot") or "layer" not in wear:
            raise ValueError(f"{path}: missing outfit slot or layer. Finish the style build before measuring.")
        self.slot, self.layer = wear["slot"], wear["layer"]
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
    ap.add_argument("--springs", action="store_true", help="simulate the pieces' spring bones (a skirt's chains) through each clip as the client does, a sixtieth of a second a step; without it they rest, as on a character the client does not simulate")
    ap.add_argument("--spring", default="", metavar="STIFFNESS,DRAG[,GRAVITY]", help="with --springs: try these values in place of the files' own, to tune them")
    ap.add_argument("--no-spring-scale", action="store_true", help="pose as a client from before the skirts' change does: a spring bone under a scaled bone does not take its scale")
    ap.add_argument("--terrain", action="store_true", help="in the ground seat's clips, place the body on the terrain as the client does and say how far the skirted pieces are under it")
    ap.add_argument("--seat-contact", action="store_true", help="give the cloth spring groups the client's ground contact in the ground seat's clips (implies --springs and --terrain)")
    ap.add_argument("--compare-client", type=Path, metavar="JOINTS.jsonl", help="compare placement against one asset-view ground-clip joint dump row and exit")
    ap.add_argument("--client-root-y", type=float, metavar="METRES", help="the client root's measured world Y on the asset-view checker")
    ap.add_argument("--ground-hips", choices=("height", "legs", "contact"), default="height", help="with --terrain: how a ground seat's clip scales the hips' height: `height` (the client's since sit-hips: hips_k blended to 1 as the clip's hips come down to the seat), `legs` (hips_k throughout, as before), `contact` (blended by the cloth contact's clip-time weight)")
    ap.add_argument("--ground-hips-band", default="", metavar="LO,HI", help="with --ground-hips height: try this band (fractions of the hips' rest height) in place of the client's")
    ap.add_argument("--heights", metavar="OUT.csv", help="with --terrain: write each ground-seat pose's hips multiplier and the pelvis and the lowest boots, trousers and skirted piece above the terrain (world mm)")
    a = ap.parse_args()
    if a.compare_client:
        if a.client_root_y is None or not np.isfinite(a.client_root_y):
            ap.error("--compare-client requires a finite --client-root-y")
        a.terrain = True
    if a.seat_contact:
        a.springs = a.terrain = True
    doc = json.load(open(a.line))
    line = doc.get("person", doc)
    if a.terrain and not (line.get("height", 0) > 0):
        ap.error("terrain placement requires a positive person height")
    type_path = os.path.join(a.types, line["type"] + ".glb")
    sk = Skeleton(type_path, line.get("proportions") or {}, float(line.get("belly", 0.0)), belly_scaled=not a.old_belly)
    library = clips_compare.clips(a.clips)[0] if (a.clip or a.compare_client) and os.path.exists(a.clips) else {}
    if a.terrain:
        terrain, scale, root_y, hips_k = terrain_fit(sk, vertical_bounds(type_path, a.styles, line), line)
        hips0 = float(sk.rest[sk.index["J_Bip_C_Hips"]][1])
    band = tuple(float(x) for x in a.ground_hips_band.split(",")) if a.ground_hips_band else GROUND_HIPS_BAND
    placed_k = [None]
    at_time = lambda tracks, t: {node: clips_compare.at(times, values, 4, t) for (node, path), (times, values) in tracks.items() if path == "rotation"}

    def posed_at(name, tracks, t):
        """The bones at time t of a clip: on the terrain (the hips' place keyed) in a ground seat's clip with `--terrain`."""
        hips = tracks.get(("J_Bip_C_Hips", "translation"))
        placed = a.terrain and name in SEAT_RATE
        if placed:
            # characters.rs `hips` scales the whole local translation, keyed or at rest, by
            # hips_k, and in a ground seat's clip its height by `ground_hips_k`.
            local = np.array(clips_compare.at(hips[0], hips[1], 3, t) if hips else sk.rest[sk.index["J_Bip_C_Hips"]], float)
            k_y = ground_hips_k(a.ground_hips, name, t, float(local[1]), hips_k, hips0, band)
            placed_k[0] = k_y
            sk.place_hips(local * np.array([hips_k, k_y, hips_k]))
        out = sk.pose(at_time(tracks, t))
        if placed:
            sk.place_hips(None)
        return out

    if a.compare_client:
        try:
            row = json.loads(a.compare_client.read_text())
            file = row["file"]
            clip, _, time = row["shot"].removeprefix("clip-").partition("@")
            t = float(time.partition("-")[0])  # a shot from a view (`clip@T/VIEW`) is named `clip-NAME@T-VIEW`
            if clip not in SEAT_RATE or not np.isfinite(t) or t < 0:
                raise ValueError("expected a timed ground-clip shot")
            _, joints = posed_at(clip, library[clip], t)
            heights = [("root", root_y, a.client_root_y)]
            for bone in ("J_Bip_C_Hips", "J_Bip_L_Foot", "J_Bip_R_Foot"):
                heights.append((bone, root_y + scale * joints[bone][1], a.client_root_y + row["joints"][bone][1]))
        except (OSError, ValueError, KeyError, TypeError, IndexError) as e:
            ap.error(f"invalid client comparison input: {e}")
        print(f"{file} {row['shot']} (world Y in mm)")
        for name, tool_y, client_y in heights:
            print(f"{name:14s} tool {tool_y * 1000:9.4f}  client {client_y * 1000:9.4f}  delta {(tool_y - client_y) * 1000:+.4f}")
        return int(any(not abs(tool_y - client_y) <= 0.001 for _, tool_y, client_y in heights))

    pieces = [Piece(os.path.join(a.styles, "outfit", n + ".glb")) for n in line["styles"]["outfit"]]
    pairs = [(i, o) for i in pieces for o in pieces if over(i, o)]
    springs = Springs([os.path.join(a.styles, "outfit", n + ".glb") for n in line["styles"]["outfit"]], scaled=not a.no_spring_scale)
    if not springs.joints:
        springs = None
    elif a.spring:
        v = [float(x) for x in a.spring.split(",")]
        for g in springs.groups:
            g.update(stiffness=v[0], drag=v[1], gravity=np.array([0.0, -1.0, 0.0]) * (v[2] if len(v) > 2 else 0.0))
    loops = {c["name"]: c.get("kind") == "loop" for c in json.load(open(os.path.join(HERE, "..", "blender", "clips.json")))["clips"]}

    def contact(name, t):
        w = seat_of(name, t, SEAT_RATE.get(name, 1.0)) if a.seat_contact else None
        # live.rs:253–271, 1096–1105 fixes the anchor 0.39 m behind the drawn body
        # for the sit and rise. On the level floor (view.rs:555–562), this is the
        # same horizontal plane at either point. characters.rs:1509–1514 lowers
        # it in world metres, so divide by the fitted root scale in model space.
        return terrain - SEAT_SINK * (1 - w) / scale if w else None

    def poses():
        """(clip, time, the bones' frames, the bones' places, the spring bones' frames or None), pose by pose."""
        mats, joints = sk.pose({})
        yield "rest", 0.0, mats, joints, (dict(springs.step(sk, 0, fresh=True)) if springs else None)
        for name in [c for c in a.clip.split(",") if c]:
            tracks = library.get(name)
            if tracks is None:
                ap.error(f"no clip {name!r} in {a.clips}")
            length = max(t[0][-1] for t in tracks.values())
            # The ground seat's clips at the client's rates, with --terrain (getting up at 1.6).
            rate = SEAT_RATE.get(name, 1.0) if a.terrain else 1.0
            if springs and a.springs:
                # The clip played from its start a sixtieth of a second a step, the springs
                # following; a loop is played once round first, and measured on its second turn.
                steps = max(int(round(length / (STEP * rate))), 1)
                first = steps if loops.get(name) else 0
                want = {first + int(round(f * steps / a.frames)) for f in range(a.frames)}
                for n in range(first + steps):
                    t = (n % steps) * STEP * rate
                    mats, joints = posed_at(name, tracks, t)
                    out = springs.step(sk, 1, fresh=n == 0, contact=contact(name, t))
                    if n in want:
                        yield name, t, mats, joints, dict(out)
            else:
                for f in range(a.frames):
                    t = length * f / a.frames
                    mats, joints = posed_at(name, tracks, t)
                    yield name, t, mats, joints, (dict(springs.step(sk, 0, fresh=True)) if springs else None)

    worst, swing, seats, count = {}, {}, {}, 0
    heights = []
    for clip, t, mats, joints, sprung in poses():
        count += 1
        axis = axis_points(joints)
        posed = {p.name: p.posed(mats, sprung) for p in pieces}
        if sprung is not None and a.springs:
            # How far the springs carry the cloth from where it rides unsimulated.
            for p in pieces:
                d = float(np.linalg.norm(posed[p.name] - p.posed(mats, dict(springs_rest(springs, sk))), axis=1).max()) * 1000
                swing[clip] = max(swing.get(clip, 0.0), d)
        if a.terrain and clip in SEAT_RATE:
            # Under the terrain the client draws, in every pose of the ground seat's clips.
            for p in pieces:
                if p.name.startswith(OUTER):
                    below = terrain - posed[p.name][:, 1]
                    r = seats.setdefault((p.name, clip, "terrain"), dict(below=0.0, behind=0.0, vertices=0))
                    r.update(below=max(r["below"], 1000 * float(below.max(initial=0.0))), vertices=max(r["vertices"], int((below > 0.005).sum())))
        if a.heights and a.terrain and clip in SEAT_RATE:
            low = lambda pre: min((float(posed[p.name][:, 1].min()) for p in pieces if p.name.startswith(pre)), default=float("nan"))
            mm = lambda y: (y - terrain) * scale * 1000
            heights.append(dict(clip=clip, t=round(t, 4), hips_k=placed_k[0], pelvis_mm=mm(joints["J_Bip_C_Hips"][1]), boots_mm=mm(low("boots")), trousers_mm=mm(low("trousers")), garment_mm=mm(low(OUTER))))
        if clip in SEATED or clip in GROUND:
            for name, (below, behind, n) in (chair(pieces, posed, mats, joints) if clip in SEATED else ground(pieces, posed)).items():
                r = seats.setdefault((name, clip, "seat"), dict(below=0.0, behind=0.0, vertices=0))
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
    for (name, clip, kind), r in sorted(seats.items()):
        fault = a.chair is not None and max(r["below"], r["behind"]) > a.chair
        bad += fault
        if fault or not a.quiet:
            if kind == "terrain":
                print(f"{name:16s} {clip}: terrain   {r['below']:6.1f} mm below")
            elif clip in SEATED:
                print(f"{name:16s} {clip}: seat top  {r['below']:6.1f} mm below")
                print(f"{name:16s} {clip}: seat back {r['behind']:6.1f} mm behind")
            else:
                print(f"{name:16s} {clip}: ground    {r['below']:6.1f} mm below")
            print(f"  {r['vertices']} vertices beyond 5 mm at most in one pose" + ("; exceeds contact limit" if fault else ""))
    if a.heights:
        import csv
        with open(a.heights, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["clip", "t", "hips_k", "pelvis_mm", "boots_mm", "trousers_mm", "garment_mm"])
            w.writeheader()
            w.writerows(heights)
    if a.json:
        json.dump(dict({f"{i}|{o}|{clip}": r for (i, o, clip), r in worst.items()}, **{f"{name}|{'terrain' if kind == 'terrain' else 'chair' if clip in SEATED else 'ground'}|{clip}": dict(most=max(r["below"], r["behind"]), **r) for (name, clip, kind), r in seats.items()}), open(a.json, "w"), indent=1)
    if swing:
        print("cloth_check: springs simulated; the cloth is carried at most " + ", ".join(f"{v:.0f} mm in {c}" for c, v in swing.items()) + " from where it rides at rest")
    print(f"cloth_check: {len(pairs)} pairs of pieces over {count} poses: " + (f"{cloth_bad} pair/clip results come through by more than {a.least} mm" if cloth_bad else f"none comes through by more than {a.least} mm"))
    if bad > cloth_bad:
        print(f"cloth_check: {bad - cloth_bad} seat or ground results exceed {a.chair} mm")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
