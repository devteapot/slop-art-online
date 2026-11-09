"""A procedural quadruped: skeleton, two-bone legs, gaits, armature, lofted skinned mesh, keyed
clips, paw markers and export. `wolf.py` and `deer.py` give a species' proportions, clips and
body; this module is the machinery they share (no species numbers here).

Each clip is a function from normalised time to the skeleton's joint points, in the animal's own
frame (forward, left, up, metres, the ground at up = 0). Legs are solved with two-bone IK in
their own vertical plane: a planted paw stays where it touched down while the body passes over
it, so a clip's natural speed is exact and feet don't slide. Bones are set from their joints'
points and keyed (rotation and location, linear, 30 fps), one action per clip in its own NLA
track, the way `animate.py` exports the characters' library.

Every species has the same bones (`BONES`: hips, spine, chest, neck, head, jaw, three tail bones,
three per leg; `paw.<leg>` ends at the paw or hoof), so the game client treats them alike.

The body is a few lofted, low-poly parts in one mesh, vertex-coloured on a white `Body` material
(the client swaps it for its shared vertex-colour toon), skinned by distance to each part's own
bones. It faces +Z in glTF (like the characters) and stands with its origin on the ground.

The summary (`<name>.clips.json`) gives every clip's length, loop, frames, paw contact windows
(`contacts`: per paw, normalised clip time, detected from paw height and world speed,
[`paw_markers`]), and for gaits their natural speed and `sync`: every gait brings the left hind
paw down at phase 0, so the game blends them at one shared phase.
"""

import json
import math

import bmesh
import bpy
from mathutils import Matrix, Vector

FPS = 30


def P(f, s, u):
    """The animal's frame (forward, left, up) in Blender's: it faces -Y, so glTF +Z."""
    return Vector((s, -f, u))


def lerp(a, b, t):
    return a + (b - a) * t


def lerp_c(a, b, t):
    t = min(1.0, max(0.0, t))
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def smooth(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def bump(t, a, b):
    """0 outside a..b, rising and falling smoothly inside."""
    if t <= a or t >= b:
        return 0.0
    return math.sin(math.pi * (t - a) / (b - a))


def dist2(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def rot2(v, a):
    c, s = math.cos(a), math.sin(a)
    return (v[0] * c - v[1] * s, v[0] * s + v[1] * c)


def ik2(root, target, a, b, forward_knee):
    """Two-bone IK in a leg's (forward, up) plane: the middle joint, bent forward or back."""
    dx, du = target[0] - root[0], target[1] - root[1]
    d = math.hypot(dx, du)
    d = min(max(d, abs(a - b) + 1e-3), a + b - 1e-4)
    ex, eu = dx / max(math.hypot(dx, du), 1e-6), du / max(math.hypot(dx, du), 1e-6)
    x = (a * a - b * b + d * d) / (2 * d)
    y = math.sqrt(max(a * a - x * x, 0.0))
    px, pu = -eu, ex  # perpendicular toward forward for a downward leg
    if not forward_knee:
        px, pu = -px, -pu
    return (root[0] + ex * x + px * y, root[1] + eu * x + pu * y)


LEGS = {  # name: (front, side sign)
    "fl": (True, 1.0), "fr": (True, -1.0), "hl": (False, 1.0), "hr": (False, -1.0),
}

# Bones: name -> (head joint, tail joint, parent). Joint names with a leg prefix are per leg.
BONES = [
    ("root", None, None, None),
    ("hips", "pelvis", "mid", "root"),
    ("spine", "mid", "chest", "hips"),
    ("chest", "chest", "neck", "spine"),
    ("neck", "neck", "skull", "chest"),
    ("head", "skull", "nose", "neck"),
    ("jaw", "jaw0", "jaw1", "head"),
    ("tail1", "tail0", "tail1", "hips"),
    ("tail2", "tail1", "tail2", "tail1"),
    ("tail3", "tail2", "tail3", "tail2"),
]
for _leg, (_front, _) in LEGS.items():
    if _front:
        BONES += [(f"upper.{_leg}", f"{_leg}.shoulder", f"{_leg}.elbow", "chest"),
                  (f"fore.{_leg}", f"{_leg}.elbow", f"{_leg}.wrist", f"upper.{_leg}"),
                  (f"paw.{_leg}", f"{_leg}.wrist", f"{_leg}.fpaw", f"fore.{_leg}")]
    else:
        BONES += [(f"thigh.{_leg}", f"{_leg}.hip", f"{_leg}.stifle", "hips"),
                  (f"shin.{_leg}", f"{_leg}.stifle", f"{_leg}.hock", f"thigh.{_leg}"),
                  (f"paw.{_leg}", f"{_leg}.hock", f"{_leg}.hpaw", f"shin.{_leg}")]


class Pose:
    """Joint points of one frame, in the animal's frame (f, s, u)."""

    def __init__(self):
        self.pt = {}

    def set(self, name, f, u, s=0.0):
        self.pt[name] = (f, s, u)


class Skeleton:
    """A species' skeleton at rest and how its body and legs move.

    `rest`: joint -> (forward, up) for the spine, head, jaw, tail and one front and one hind leg
    (shoulder, elbow, wrist, fpaw; hip, stifle, hock, hpaw). `side`: the legs' lateral offset.
    `centre`: the point (forward, up) the body pitches about. `pastern_follow`: how much the
    pastern (or cannon) turns with the leg as a planted paw passes under the body (0 keeps it as
    at rest, the wolf's; long-legged animals need it so the leg reaches). `neck_bend` and
    `head_bend`: how far the neck and the head turn down per unit of `body_pose`'s head lowering.
    `fore_fold`: which way a swinging front paw folds. `fit`: keep every leg within its length
    by turning the pastern toward the leg's line where it has to (off for the wolf, as made).
    `scapula`: how far the shoulder slides with the front paw's way from neutral."""

    def __init__(self, rest, side, centre, pastern_follow=0.0, neck_bend=0.9, head_bend=0.6, fore_fold=1.0, fit=False, scapula=0.0):
        self.REST = rest
        self.SIDE = side
        self.centre = centre
        self.follow = pastern_follow
        # Which way a swinging front paw folds: +1 turns it forward (the wolf's, as made), -1
        # back under the knee, as a hoof folds.
        self.fore_fold = fore_fold
        # Turn the pastern toward the leg's line, as little as needed, when the leg would
        # otherwise have to reach further than it is long.
        self.fit = fit
        # The shoulder slides with the front leg's swing (the shoulder blade turns), this share
        # of the paw's way forward or back from neutral.
        self.scapula = scapula
        self.neck_bend = neck_bend
        self.head_bend = head_bend
        R = rest
        self.LEN = {
            "upper": dist2(R["shoulder"], R["elbow"]), "fore": dist2(R["elbow"], R["wrist"]),
            "thigh": dist2(R["hip"], R["stifle"]), "shin": dist2(R["stifle"], R["hock"]),
        }
        # Paw offsets from the wrist / hock at rest (pastern and metatarsus).
        self.PASTERN = (R["fpaw"][0] - R["wrist"][0], R["fpaw"][1] - R["wrist"][1])
        self.META = (R["hpaw"][0] - R["hock"][0], R["hpaw"][1] - R["hock"][1])
        # The leg's lean at rest (shoulder or hip to paw, from vertical, + forward).
        self.lean0 = {True: math.atan2(R["fpaw"][0] - R["shoulder"][0], R["shoulder"][1] - R["fpaw"][1]),
                      False: math.atan2(R["hpaw"][0] - R["hip"][0], R["hip"][1] - R["hpaw"][1])}

    def body_pose(self, bob=0.0, pitch=0.0, lean=0.0, flex=0.0, shift=0.0, head=(0.0, 0.0), head_turn=0.0, jaw=0.0, tail=(0.0, 0.0), crouch=0.0):
        """The torso, head and tail: `bob` lifts it, `pitch` tips it nose-down (+, radians) about
        its centre, `flex` arches the back (+) or stretches it (-), `shift` slides it forward,
        `head` (lower, reach) moves the head down and out, `head_turn` turns it left (radians),
        `jaw` opens the mouth (radians), `tail` (raise, sway) in radians, `crouch` lowers the
        hind and front ends (m). Returns a Pose without legs and a function placing body-fixed
        points."""
        REST = self.REST
        p = Pose()
        cf, cu = self.centre

        def place(f, u, lift=0.0):
            rf, ru = rot2((f - cf, u - cu), -pitch)
            return (cf + rf + shift, cu + ru + bob + lift - crouch)

        for k in ("pelvis", "mid", "chest", "neck", "tail0"):
            f, u = REST[k]
            lift = {"mid": flex * 0.06, "pelvis": -flex * 0.02, "chest": -flex * 0.02}.get(k, 0.0)
            if k in ("pelvis", "tail0"):
                f += flex * 0.05
            if k == "chest":
                f -= flex * 0.05
            p.set(k, *place(f, u, lift))
        # Neck and head: lowered (`head[0]`) and reaching out (`head[1]`), turned by head_turn.
        nf, _, nu = p.pt["neck"]
        sf, su = REST["skull"][0] - REST["neck"][0], REST["skull"][1] - REST["neck"][1]
        neck_a = -head[0] * self.neck_bend - pitch
        sf, su = rot2((sf * (1 + head[1]), su), neck_a)
        ts = math.sin(head_turn) * math.hypot(sf, su)
        sf *= math.cos(head_turn) ** 0.5
        p.set("skull", nf + sf, nu + su, ts)
        kf, ks, ku = p.pt["skull"]
        head_a = -head[0] * self.head_bend - pitch
        for k in ("nose", "jaw0", "jaw1"):
            df, du = REST[k][0] - REST["skull"][0], REST[k][1] - REST["skull"][1]
            if k == "jaw1":
                # The jaw swings down about its hinge (jaw0).
                jf, ju = REST["jaw0"][0] - REST["skull"][0], REST["jaw0"][1] - REST["skull"][1]
                rf, ru = rot2((df - jf, du - ju), -jaw)
                df, du = jf + rf, ju + ru
            df, du = rot2((df, du), head_a)
            p.set(k, kf + df * math.cos(head_turn), ku + du, ks + df * math.sin(head_turn))
        # Tail: hanging in a curve, raised and swayed.
        tf, _, tu = p.pt["tail0"]
        prev = (tf, 0.0, tu)
        for i, k in enumerate(("tail1", "tail2", "tail3")):
            a, b = REST[("tail0", "tail1", "tail2")[i]], REST[k]
            df, du = rot2((b[0] - a[0], b[1] - a[1]), tail[0] * (0.6 + 0.4 * i) - pitch)
            ds = math.sin(tail[1] * (0.5 + 0.5 * i)) * abs(df)
            prev = (prev[0] + df, prev[1] + ds, prev[2] + du)
            p.pt[k] = prev
        return p, place

    def leg_points(self, p, place, leg, paw, lift_paw=0.0, fold=0.0):
        """Solve one leg to put its paw (f, u) at `paw`; `fold` bends the wrist or hock (radians,
        swing phase), `lift_paw` raises the toe. Writes the leg's joints into the pose."""
        REST, LEN = self.REST, self.LEN
        front, sgn = LEGS[leg]
        s = self.SIDE * sgn
        if front:
            root = place(*REST["shoulder"])
            if self.scapula:
                root = (root[0] + self.scapula * (paw[0] - REST["fpaw"][0]), root[1])
            off = rot2(self.PASTERN, fold * self.fore_fold + self._turn(root, paw, True) if self.follow else fold)
            if self.fit:
                off = self._fitted(root, paw, off, LEN["upper"] + LEN["fore"])
            wrist = (paw[0] - off[0], paw[1] - off[1])
            elbow = ik2(root, wrist, LEN["upper"], LEN["fore"], forward_knee=False)
            names = ("shoulder", "elbow", "wrist", "fpaw")
            pts = (root, elbow, wrist, paw)
        else:
            root = place(*REST["hip"])
            off = rot2(self.META, -fold + self._turn(root, paw, False) if self.follow else -fold)
            if self.fit:
                off = self._fitted(root, paw, off, LEN["thigh"] + LEN["shin"])
            hock = (paw[0] - off[0], paw[1] - off[1])
            stifle = ik2(root, hock, LEN["thigh"], LEN["shin"], forward_knee=True)
            names = ("hip", "stifle", "hock", "hpaw")
            pts = (root, stifle, hock, paw)
        for n, q in zip(names, pts):
            p.set(f"{leg}.{n}", q[0], q[1], s)

    def _fitted(self, root, paw, off, reach):
        """`off` (the joint above the paw to the paw) turned toward the root–paw line just far
        enough that the joint is within `reach` of the root (or onto the line, if even that is
        too far)."""
        limit = reach * 0.995
        far = lambda o: math.hypot(paw[0] - o[0] - root[0], paw[1] - o[1] - root[1])  # noqa: E731
        if far(off) <= limit:
            return off
        line = math.atan2(paw[1] - root[1], paw[0] - root[0])
        have = math.atan2(off[1], off[0])
        full = (line - have + math.pi) % (2 * math.pi) - math.pi
        if far(rot2(off, full)) > limit:
            return rot2(off, full)
        lo, hi = 0.0, 1.0
        for _ in range(24):
            mid = (lo + hi) / 2
            if far(rot2(off, full * mid)) > limit:
                lo = mid
            else:
                hi = mid
        return rot2(off, full * hi)

    def _turn(self, root, paw, front):
        """How far the pastern turns with the leg's lean (radians, + toward forward at the paw)."""
        lean = math.atan2(paw[0] - root[0], max(root[1] - paw[1], 1e-3))
        return self.follow * (lean - self.lean0[front])

    def neutral_paw(self, leg):
        return self.REST["fpaw"] if LEGS[leg][0] else self.REST["hpaw"]

    def gait(self, t, speed, period, offsets, duty, lift, body, fold=1.1):
        """A cyclic gait at `speed` m/s: each leg's paw is planted for `duty` of the cycle and
        moves back under the body at exactly `speed`, then swings forward."""
        p, place = body
        reach = speed * period * duty  # ground covered while a paw is down
        for leg, off in offsets.items():
            ph = (t + off) % 1.0
            f0, u0 = self.neutral_paw(leg)
            if ph < duty:
                x = ph / duty
                f = f0 + reach * (0.5 - x)
                paw, fl = (f, u0), 0.0
            else:
                x = (ph - duty) / (1 - duty)
                e = smooth(x)
                f = f0 + reach * (e - 0.5)
                h = lift * math.sin(math.pi * x) ** 0.8
                paw, fl = (f, u0 + h), fold * math.sin(math.pi * min(1.0, x * 1.3))
            self.leg_points(p, place, leg, paw, fold=fl)
        return p

    def stand(self, body):
        p, place = body
        for leg in LEGS:
            self.leg_points(p, place, leg, self.neutral_paw(leg))
        return p

    def lie_down(self, p, roll):
        """Roll a pose onto its right side about the forward axis by `roll` (0-1), settling its
        lowest point on the ground and keeping it centred where it stood."""
        ang = roll * math.pi / 2 * 0.97
        pivot = 0.0
        out = Pose()
        for k, (f, sd, u) in p.pt.items():
            uu = u - pivot
            s2 = sd * math.cos(ang) - uu * math.sin(ang)
            u2 = sd * math.sin(ang) + uu * math.cos(ang) + pivot
            out.pt[k] = (f, s2, u2)
        low = min(q[2] for q in out.pt.values())
        cs = out.pt["mid"][1]
        for k, (f, sd, u) in out.pt.items():
            out.pt[k] = (f, sd - cs * roll, u - low * roll)
        return out

    def stretch(self, pose):
        """How far the legs' lower bones fall short of their joints (m, worst leg): a leg asked
        to reach further than it is long."""
        worst = 0.0
        for leg, (front, _) in LEGS.items():
            a, b, c = ("shoulder", "elbow", "wrist") if front else ("hip", "stifle", "hock")
            la, lb = (self.LEN["upper"], self.LEN["fore"]) if front else (self.LEN["thigh"], self.LEN["shin"])
            ra, rb, rc = (pose.pt[f"{leg}.{n}"] for n in (a, b, c))
            got = math.dist((ra[0], ra[2]), (rb[0], rb[2])) + math.dist((rb[0], rb[2]), (rc[0], rc[2]))
            worst = max(worst, got - (la + lb))
        return worst


# ---------------------------------------------------------------------------------------------
# Armature


def bone_matrix(head, tail):
    """Armature-space matrix of a bone from its head and tail (Blender coords): Y along it, X
    toward the animal's left where it can be."""
    y = (tail - head).normalized()
    side = Vector((1, 0, 0))
    x = side - y * side.dot(y)
    if x.length < 1e-4:
        x = Vector((0, 0, 1)) - y * y.z
    x.normalize()
    z = x.cross(y)
    m = Matrix((x, y, z)).transposed().to_4x4()
    m.translation = head
    return m


def joint(pose, name):
    f, s, u = pose.pt[name]
    return P(f, s, u)


def bone_ends(pose, b):
    _, h, t, _ = b
    if h is None:
        return P(0, 0, 0), P(0.2, 0, 0)
    return joint(pose, h), joint(pose, t)


def make_armature(rest, name, rig):
    arm_data = bpy.data.armatures.new(rig)
    arm = bpy.data.objects.new(name, arm_data)
    bpy.context.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    ebs = {}
    for b in BONES:
        bname, _, _, parent = b
        head, tail = bone_ends(rest, b)
        eb = arm_data.edit_bones.new(bname)
        eb.head, eb.tail = head, tail
        eb.matrix = bone_matrix(head, tail)
        eb.length = (tail - head).length
        eb.use_deform = bname != "root"
        if parent:
            eb.parent = ebs[parent]
            eb.use_connect = False
        ebs[bname] = eb
    bpy.ops.object.mode_set(mode="OBJECT")
    return arm


# ---------------------------------------------------------------------------------------------
# Mesh


def loft(bm, stations, sides=8, cap0=True, cap1=True, phase=0.0):
    """Rings at `stations` [(centre Vector, along Vector, half width, half height)], joined
    into a tube. Rings lie across `along`; width runs along the animal's side (X)."""
    rings = []
    for c, along, w, h in stations:
        a = along.normalized()
        x = Vector((1, 0, 0)) - a * a.x
        if x.length < 1e-3:
            x = Vector((0, 1, 0)) - a * a.y
        x.normalize()
        y = a.cross(x).normalized()
        ring = []
        for i in range(sides):
            t = 2 * math.pi * (i + phase) / sides
            ct, st = math.cos(t), math.sin(t)
            # A soft superellipse: fuller than an ellipse, so the low-poly body reads as mass.
            r = (abs(ct) ** 2.6 + abs(st) ** 2.6) ** (-1 / 2.6)
            ring.append(bm.verts.new(c + x * (ct * w * r) + y * (st * h * r)))
        rings.append(ring)
    faces = []
    for r0, r1 in zip(rings, rings[1:]):
        for i in range(sides):
            j = (i + 1) % sides
            faces.append(bm.faces.new((r0[i], r0[j], r1[j], r1[i])))
    if cap0:
        faces.append(bm.faces.new(list(reversed(rings[0]))))
    if cap1:
        faces.append(bm.faces.new(rings[-1]))
    return [v for r in rings for v in r], faces


def path_stations(points, sizes):
    """Stations along a polyline of Vectors with (w, h) per point."""
    out = []
    for i, (c, (w, h)) in enumerate(zip(points, sizes)):
        a = points[min(i + 1, len(points) - 1)] - points[max(i - 1, 0)]
        out.append((c, a, w, h))
    return out


class Part:
    def __init__(self, bm, verts, faces, bones, color):
        self.verts, self.faces, self.bones, self.color = verts, faces, bones, color


def seg_dist(p, a, b):
    ab = b - a
    t = max(0.0, min(1.0, (p - a).dot(ab) / max(ab.dot(ab), 1e-9)))
    return (p - (a + ab * t)).length


def make_mesh(rest, arm, build_mesh, name):
    """The body from `build_mesh(rest) -> (bmesh, [Part])`, coloured and skinned to `arm`."""
    bm, parts = build_mesh(rest)
    col = bm.loops.layers.color.new("Color")
    for part in parts:
        for fc in part.faces:
            fc.smooth = True
            for loop in fc.loops:
                loop[col] = (*part.color(loop.vert.co, fc.normal), 1.0)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    me = bpy.data.meshes.new(name)
    # Weights from each part's own bones, by distance to their segments.
    ends = {b[0]: bone_ends(rest, b) for b in BONES}
    weights = {}
    for part in parts:
        for v in part.verts:
            ds = [(seg_dist(v.co, *ends[b]), b) for b in part.bones]
            ds.sort()
            ws = [(1.0 / (d + 0.015) ** 4, b) for d, b in ds[:3]]
            tot = sum(w for w, _ in ws)
            weights[v] = [(w / tot, b) for w, b in ws if w / tot > 0.02]
    bm.verts.index_update()
    vw = {v.index: w for v, w in weights.items()}
    bm.to_mesh(me)
    bm.free()
    # The exporter writes the active colour attribute (export_vertex_color="ACTIVE").
    me.color_attributes.active_color = me.color_attributes["Color"]
    me.color_attributes.render_color_index = me.color_attributes.active_color_index
    obj = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(obj)
    mat = bpy.data.materials.new("Body")
    mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = (1, 1, 1, 1)
    bsdf.inputs["Roughness"].default_value = 0.9
    me.materials.append(mat)
    groups = {b[0]: obj.vertex_groups.new(name=b[0]) for b in BONES if b[0] != "root"}
    for i, ws in vw.items():
        tot = sum(w for w, _ in ws)
        for w, b in ws:
            groups[b].add([i], w / tot, "REPLACE")
    obj.parent = arm
    mod = obj.modifiers.new("Rig", "ARMATURE")
    mod.object = arm
    return obj


# ---------------------------------------------------------------------------------------------
# Keying and markers


def key_clip(arm, name, seconds, fn, loop):
    n = max(2, round(seconds * FPS))
    frames = n if loop else n + 1
    rest = {b.name: b.matrix_local.copy() for b in arm.data.bones}
    parent = {b[0]: b[3] for b in BONES}
    act = bpy.data.actions.new(name)
    arm.animation_data_create()
    arm.animation_data.action = act
    seq = {b[0]: [] for b in BONES}
    for i in range(frames + (1 if loop else 0)):
        t = (i % n) / n if loop else i / n
        pose = fn(t)
        M = {}
        for b in BONES:
            head, tail = bone_ends(pose, b)
            M[b[0]] = bone_matrix(head, tail)
        for b in BONES:
            bn = b[0]
            par = parent[bn]
            if par:
                local = (M[par] @ rest[par].inverted() @ rest[bn]).inverted() @ M[bn]
            else:
                local = rest[bn].inverted() @ M[bn]
            seq[bn].append(local)
    for bn, mats in seq.items():
        pb = arm.pose.bones[bn]
        pb.rotation_mode = "QUATERNION"
        qs, ls = [], []
        prev = None
        for m in mats:
            q = m.to_quaternion()
            if prev is not None and prev.dot(q) < 0:
                q = -q
            prev = q
            qs.append(q)
            ls.append(m.to_translation())
        for path, comps in ((pb.path_from_id("rotation_quaternion"), [[q.w for q in qs], [q.x for q in qs], [q.y for q in qs], [q.z for q in qs]]),
                            (pb.path_from_id("location"), [[v.x for v in ls], [v.y for v in ls], [v.z for v in ls]])):
            for k, comp in enumerate(comps):
                fc = act.fcurve_ensure_for_datablock(arm, path, index=k, group_name=bn)
                fc.keyframe_points.add(len(comp))
                fc.keyframe_points.foreach_set("co", [x for f, v in enumerate(comp) for x in (f, v)])
                for kp in fc.keyframe_points:
                    kp.interpolation = "LINEAR"
                fc.update()
    arm.animation_data.action = None
    track = arm.animation_data.nla_tracks.new()
    track.name = name
    strip = track.strips.new(name, 0, act)
    strip.name = name
    act.use_fake_user = True
    return len(seq["root"])


def paw_name(leg):
    return f"{leg}.{'fpaw' if LEGS[leg][0] else 'hpaw'}"


def paw_slide(sk, fn, speed, period):
    """How far a planted paw drifts (m) between samples, at worst: its world-space travel while it
    is on the ground (within 2 mm of its rest height), against the body moving at `speed`."""
    worst = 0.0
    n = 240
    for leg in LEGS:
        name = paw_name(leg)
        prev = None
        for i in range(n + 1):
            t = i / n
            f, _, u = fn(t).pt[name]
            world = f + speed * period * t
            ground = sk.neutral_paw(leg)[1] + 0.002
            if u < ground and prev is not None and prev[1] < ground:
                worst = max(worst, abs(world - prev[0]))
            prev = (world, u)
    return worst


def paw_markers(sk, fn, seconds, speed, loop):
    """Each paw's contact windows (normalised clip time), detected from the clip as baked: the paw
    within 1 cm of its rest height and slower than 0.3 m/s in the world (the body moving at
    `speed`). Loops' windows that cross the seam are split at 1. The gaits all bring the left hind
    paw down at 0 (the gait offsets), the phase the game syncs them on (`sync: "hl"`)."""
    n = max(2, round(seconds * FPS))
    frames = n if loop else n + 1
    out = {}
    for leg in LEGS:
        name = paw_name(leg)
        rest_u = sk.neutral_paw(leg)[1]
        pts = []
        for i in range(frames + 1):
            f, _, u = fn((i % n) / n if loop else min(i, n) / n).pt[name]
            pts.append((f + (speed or 0.0) * seconds * i / n, u))
        down = []
        for i in range(frames):
            (f0, u0), (f1, _) = pts[i], pts[i + 1] if (loop or i + 1 < frames) else pts[i]
            down.append(u0 - rest_u <= 0.01 and abs(f1 - f0) * FPS <= 0.3)
        wins, i = [], 0
        while i < frames:
            if down[i]:
                j = i
                while j < frames and down[j]:
                    j += 1
                wins.append([i / n, min(j / n, 1.0)])
                i = j
            else:
                i += 1
        # A loop's window that runs to its end continues at 0: one contact, split at the seam.
        out[leg] = [[round(a, 4), round(b, 4)] for a, b in wins]
    return out


# ---------------------------------------------------------------------------------------------
# The whole file


def build(sk, model, clips, build_mesh, out, summary_path, withers_range, extra=None, label=None, stretch=False):
    """Make the rig, body and clips and export `out` (GLB); write the summary.

    `clips`: name -> (seconds, loop, natural speed m/s or None, fn(t) -> Pose). `withers_range`:
    the forward band (Blender -y) where the shoulder height is measured. `extra(name, rec)` adds
    fields to a clip's summary. `stretch`: also report each clip's worst leg overreach."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    # Keys are at FPS; the exporter times them at the scene's rate (Blender's default is 24, which
    # made every clip 1.25 × longer than the summary said).
    bpy.context.scene.render.fps = FPS
    bpy.context.scene.render.fps_base = 1.0
    label = label or model.capitalize()
    rest = sk.stand(sk.body_pose())
    arm = make_armature(rest, label, f"{label}Rig")
    body = make_mesh(rest, arm, build_mesh, f"{label}Body")
    lo, hi = withers_range
    withers = max(v.co.z for v in body.data.vertices if lo < -v.co.y < hi)
    summary = {"model": model, "fps": FPS, "faces": "+Z", "shoulder_m": round(withers, 3), "clips": []}
    for name, (seconds, loop, speed, fn) in clips.items():
        frames = key_clip(arm, name, seconds, fn, loop)
        rec = {"name": name, "seconds": round(seconds, 3), "loop": loop, "frames": frames}
        rec["contacts"] = paw_markers(sk, fn, seconds, speed, loop)
        if speed:
            rec["sync"] = "hl"
            rec["speed"] = speed
            rec["paw_slide_m"] = round(paw_slide(sk, fn, speed, seconds), 4)
        if stretch:
            rec["stretch_m"] = round(max(sk.stretch(fn(i / 60)) for i in range(61)), 4)
        if extra:
            extra(name, rec)
        summary["clips"].append(rec)
        print(f"CLIP {name}: {seconds:.2f} s, {frames} keys" + (f", {speed} m/s, paw slide {rec['paw_slide_m'] * 100:.1f} cm" if speed else "")
              + (f", leg stretch {rec['stretch_m'] * 100:.1f} cm" if stretch else ""))
    # Each paw's tip at rest in glTF coordinates (x left, y up, z forward), for measuring planted
    # paws in the baked file (`living/tools/marker_check.py`): the paw bones end there.
    summary["paw_len"] = {leg: round(math.hypot(*(sk.PASTERN if LEGS[leg][0] else sk.META)), 4) for leg in LEGS}
    summary["paw_tips"] = {leg: [round(x, 4) for x in (rest.pt[paw_name(leg)][1], rest.pt[paw_name(leg)][2], rest.pt[paw_name(leg)][0])] for leg in LEGS}
    tris = sum(len(p.vertices) - 2 for p in body.data.polygons)
    summary["triangles"] = tris
    summary["bones"] = len(BONES) - 1
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(
        filepath=out, export_format="GLB", export_yup=True, export_vertex_color="ACTIVE", export_normals=True,
        export_animations=True, export_animation_mode="NLA_TRACKS", export_force_sampling=True, export_frame_step=1,
        export_optimize_animation_size=False, export_def_bones=False, export_leaf_bone=False, export_reset_pose_bones=True,
        export_rest_position_armature=True, export_morph_animation=False, export_materials="EXPORT")
    print(f"{model.upper()} {out}: {tris} triangles, {len(BONES) - 1} bones, {len(clips)} clips")
    if summary_path:
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=1)
    return summary


def args():
    import argparse
    import sys
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--summary")
    ap.add_argument("--seed", default="1")
    return ap.parse_args(argv)
