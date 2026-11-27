"""Replace the foundation wrist rings' distal surface with shared-rig B1 hands."""

import argparse
import shutil
import sys
from array import array
from collections import defaultdict
from pathlib import Path

import numpy as np

from cage import MORPHS, nrm

TOOLS = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(TOOLS), str(TOOLS / "board")]
import glb
from merge_primitives import append_accessor, read_glb, write_glb

FINGERS = ("Index", "Middle", "Ring", "Little")
DIGITS = (*FINGERS, "Thumb")


def aligned(a, b, points):
    """Match winding and angular origin of two equal-size cross sections."""
    a = np.asarray([points[i] for i in a])
    a = a - a.mean(0)
    options = [np.roll(r, k) for r in (b, b[::-1]) for k in range(len(b))]

    def error(r):
        v = np.asarray([points[i] for i in r])
        return np.square(a - (v - v.mean(0))).sum()

    return min(options, key=error).tolist()


def hand_cage(pivots, unit):
    """B1's 24-station palm, shared interdigital webs and twelve-sided sockets."""
    points, weights, faces = [], [], []
    tips = {}
    thumb_pad = None

    def vertex(p, w):
        points.append(p)
        weights.append(w)
        return len(points) - 1

    wrist = pivots["Hand"]
    knuckles = np.array([pivots[f + "1"] for f in FINGERS])
    axis = nrm(knuckles[1] - wrist)
    across = nrm(knuckles[3] - knuckles[0])
    across = nrm(across - axis * (axis @ across))
    back = nrm(np.cross(axis, across))
    if back[1] < 0:
        back *= -1
    uv = (
        [(i / 4 - 1, 1) for i in range(9)]
        + [(1, v) for v in (0.5, 0, -0.5)]
        + [(1 - i / 4, -1) for i in range(9)]
        + [(-1, v) for v in (-0.5, 0, 0.5)]
    )
    rows = []
    # At fingertip side of the palm, each socket is centered on its own MCP.
    # Use the shared skeleton's breadth and stagger instead of Cora's A-pose.
    knuckle_line = np.array(
        [1.5 * knuckles[0] - 0.5 * knuckles[1], *knuckles, 1.5 * knuckles[-1] - 0.5 * knuckles[-2]]
    )
    for t, depth in (
        (0.12, 0.0158),
        (0.23, 0.0167),
        (0.37, 0.0185),
        (0.55, 0.0195),
        (0.77, 0.0170),
        (1.0, 0.0110),
    ):
        ring = []
        for u, v in uv:
            end = np.array(
                [np.interp(u, [-1, -0.75, -0.25, 0.25, 0.75, 1], values) for values in knuckle_line.T]
            )
            at_wrist = wrist + (0.023 * unit * u) * across
            p = (1 - t) * at_wrist + t * end
            p += back * unit * (v * depth * (1 - 0.22 * u * u) + 0.0022 * (1 - u * u) * t)
            p += axis * unit * (0.004 * t**3)
            w = {"Hand": 1.0}
            if t < 0.7:
                forearm = np.interp(t, [0.12, 0.23, 0.37, 0.55], [0.38, 0.24, 0.10, 0.025])
                w = {"Hand": 1 - forearm, "LowerArm": forearm}
            if u < 0 and t < 1:
                radial = np.clip(-u, 0, 1) ** 1.5
                thumb = radial * np.interp(
                    t, [0.12, 0.23, 0.37, 0.55, 0.77, 1], [0.00, 0.26, 0.60, 0.72, 0.33, 0]
                )
                w = {name: (1 - thumb) * weight for name, weight in w.items()}
                w["Thumb1"] = thumb
            if t == 1:
                # The centre of each web follows both adjacent knuckles.
                x = np.clip((u + 0.75) * 2, 0, 3)
                lo, hi = int(np.floor(x)), int(np.ceil(x))
                w = {"Hand": 0.43, FINGERS[lo] + "1": 0.57 * (1 - (x - lo))}
                if hi != lo:
                    w[FINGERS[hi] + "1"] = 0.57 * (x - lo)
            ring.append(vertex(p, w))
        rows.append(ring)
    for r, (a, b) in enumerate(zip(rows, rows[1:])):
        for k in range(24):
            if r in (1, 2) and k in (20, 21, 22, 23):
                continue
            q = (k + 1) % 24
            faces.append([a[k], a[q], b[q], b[k]])
    end = rows[-1]
    div = {0: [end[i] for i in (0, 23, 22, 21, 20)], 4: [end[i] for i in (8, 9, 10, 11, 12)]}
    for i in range(1, 4):
        a, b = end[2 * i], end[20 - 2 * i]
        inner = [
            vertex(
                (1 - t) * points[a] + t * points[b] + 0.004 * unit * np.sin(np.pi * t) * axis, weights[a]
            )
            for t in (0.25, 0.5, 0.75)
        ]
        div[i] = [a, *inner, b]

    def digit(name, socket, radius):
        nonlocal thumb_pad
        j1, j2, j3 = (pivots[name + str(i)] for i in range(1, 4))
        proximal, distal = nrm(j2 - j1), nrm(j3 - j2)
        root = np.mean([points[i] for i in socket], axis=0)
        tiplen = {"Thumb": 0.023, "Index": 0.022, "Middle": 0.024, "Ring": 0.022, "Little": 0.019}[
            name
        ] * unit
        pad = distal
        knuckle = distal
        pad_knuckle = distal
        crease = 0.006 * unit
        if name == "Thumb":
            # The pad faces the finger pads across the palm. Turn the section
            # frames gradually across the two creases to preserve their radius.
            j2 = j2 - 0.004 * unit * back
            j3 = j3 + unit * (0.005 * axis - 0.014 * back + 0.001 * across)
            proximal, distal = nrm(j2 - root), nrm(j3 - j2)
            pad = nrm(0.70 * axis - 0.04 * across - 0.71 * back)
            thumb_pad = pad
            knuckle, pad_knuckle = nrm(proximal + distal), nrm(distal + pad)
            crease = 0.010 * unit
        stations = [
            (root + 0.34 * (j2 - root), proximal, 1.04, 0.97, 1, 0),
            (j2 - 0.008 * unit * proximal, proximal, 0.98, 0.91, 1, 0.13),
            (j2, knuckle, 0.99, 0.94, 1, 0.50),
            (j2 + 0.008 * unit * distal, distal, 0.93, 0.89, 1, 0.87),
            (j3 - crease * distal, distal, 0.82, 0.80, 2, 0.12),
            (j3, pad_knuckle, 0.84, 0.81, 2, 0.50),
            (j3 + crease * pad, pad, 0.80, 0.76, 2, 0.88),
            (j3 + 0.70 * tiplen * pad, pad, 0.73, 0.68, 3, 0),
            (j3 + 0.94 * tiplen * pad, pad, 0.50, 0.47, 3, 0),
        ]
        prev = socket
        for center, direction, breadth, height, segment, share in stations:
            wide = nrm(across - direction * (across @ direction))
            dorsal = nrm(np.cross(wide, direction))
            if dorsal @ back < 0:
                dorsal *= -1
            w = {name + str(segment): 1 - share}
            if share:
                w[name + str(segment + 1)] = share
            if segment == 1 and share == 0:
                palm = 0.17 if name == "Thumb" else 0.10
                w = {"Hand": palm, name + "1": 1 - palm}
            if name == "Thumb":
                progress = np.clip(
                    np.linalg.norm(center - root) / np.linalg.norm(j3 + tiplen * pad - root), 0, 1
                )
                # Share a little of the palm frame through the pad. This limits
                # shear from cumulative thumb scales at a fully curled IP.
                support = {"Hand": 0.33, "Thumb1": 0.015, "Thumb2": 0.06}
                frac = sum(support.values()) * progress
                w = {k: weight * (1 - frac) for k, weight in w.items()}
                for key, val in support.items():
                    w[key] = w.get(key, 0) + val * progress
            ring = []
            for angle in np.arange(12) * (2 * np.pi / 12):
                normal = wide * breadth * np.sin(angle) + dorsal * height * np.cos(angle)
                ring.append(vertex(center + radius * unit * normal, w))
            ring = aligned(prev, ring, points)
            if name == "Thumb" and prev is socket:
                # Blend each part of the first ring from its matching web vertex.
                for old, new in zip(prev, ring):
                    weights[new] = {
                        bone: 0.4 * weights[old].get(bone, 0) + 0.6 * w.get(bone, 0)
                        for bone in weights[old].keys() | w.keys()
                    }
            for k in range(12):
                q = (k + 1) % 12
                faces.append([prev[k], prev[q], ring[q], ring[k]])
            prev = ring
        tip = vertex(j3 + tiplen * pad, w)
        tips[name] = tip
        for k in range(0, 12, 2):
            faces.append([prev[k], prev[k + 1], prev[(k + 2) % 12], tip])

    for i, name in enumerate(FINGERS):
        a = 2 * i
        rim = [*end[a : a + 3], *div[i + 1][1:], end[19 - a], end[20 - a], *div[i][-2:0:-1]]
        digit(name, rim, (0.0102, 0.0107, 0.0099, 0.0085)[i])
    thumb = (
        [rows[1][i] for i in (20, 21, 22, 23, 0)]
        + [rows[2][0], rows[3][0]]
        + [rows[3][i] for i in (23, 22, 21, 20)]
        + [rows[2][20]]
    )
    digit("Thumb", thumb, 0.012)
    return np.array(points), weights, faces, rows[0], tips, thumb_pad


def subdivide(vertices, faces, boundary):
    """One Catmull-Clark step on geometry and interpolated joint weights."""
    facepoints = vertices[np.array(faces)].mean(1)
    incidence = defaultdict(list)
    vf = defaultdict(list)
    for i, face in enumerate(faces):
        for a, b in zip(face, np.roll(face, -1)):
            incidence[tuple(sorted((a, b)))].append(i)
            vf[a].append(i)
    updated = vertices.copy()
    neighbors, border = defaultdict(list), defaultdict(list)
    midpoints, edgeids = [], {}
    for (a, b), adj in incidence.items():
        assert len(adj) in (1, 2)
        neighbors[a].append(b)
        neighbors[b].append(a)
        p = vertices[a] + vertices[b]
        if len(adj) == 1:
            border[a].append(b)
            border[b].append(a)
            midpoints.append(p / 2)
        else:
            midpoints.append((p + facepoints[adj].sum(0)) / 4)
        edgeids[a, b] = len(vertices) + len(midpoints) - 1
    for i, connected in neighbors.items():
        if i in border:
            updated[i] = 0.75 * vertices[i] + 0.25 * vertices[border[i]].mean(0)
        else:
            n = len(connected)
            updated[i] = (
                (n - 2) * vertices[i] + vertices[connected].mean(0) + facepoints[vf[i]].mean(0)
            ) / n
    out = []

    def edge(a, b):
        return edgeids[tuple(sorted((a, b)))]

    for i, f in enumerate(faces):
        for k, a in enumerate(f):
            out.append(
                [a, edge(a, f[(k + 1) % 4]), len(vertices) + len(midpoints) + i, edge(f[k - 1], a)]
            )
    rim = [v for a, b in zip(boundary, np.roll(boundary, -1)) for v in (a, edge(a, b))]
    return np.vstack([updated, midpoints, facepoints]), out, rim


def edge_set(tris):
    pairs = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    return set(map(tuple, np.sort(pairs, axis=1)))


def stitch(outer, inner, p):
    """March both wrist loops by angle, preserving every forearm boundary edge."""
    c = p[inner].mean(0)
    axis = nrm(c - p[outer].mean(0))
    u = nrm(p[inner[0]] - c - axis * ((p[inner[0]] - c) @ axis))
    v = np.cross(axis, u)

    def around(loop):
        offset = p[loop] - p[loop].mean(0)
        angle = np.arctan2(offset @ v, offset @ u) % (2 * np.pi)
        order = angle.argsort()
        return np.array(loop)[order], angle[order]

    a, aa = around(outer)
    b, bb = around(inner)
    i = j = 0
    faces = []
    while i < len(a) or j < len(b):
        if j == len(b) or (i < len(a) and aa[i] <= bb[j]):
            faces.append([a[i - 1], a[i], b[j - 1]])
            i += 1
        else:
            faces.append([a[i - 1], b[j], b[j - 1]])
            j += 1
    return faces


def orient(tris, p, wrist):
    """Propagate common winding across the webs and point the skin outwards."""
    links = defaultdict(list)
    for i, f in enumerate(tris):
        for a, b in zip(f, np.roll(f, -1)):
            links[tuple(sorted((a, b)))].append((i, a < b))
    adj = defaultdict(list)
    for pair in links.values():
        assert len(pair) <= 2
        if len(pair) == 2:
            (i, a), (j, b) = pair
            adj[i].append((j, a == b))
            adj[j].append((i, a == b))
    flip = {0: False}
    todo = [0]
    while todo:
        i = todo.pop()
        for j, rev in adj[i]:
            sign = flip[i] ^ rev
            if j in flip:
                assert flip[j] == sign
            else:
                flip[j] = sign
                todo.append(j)
    assert len(flip) == len(tris)
    tris = np.array([f[::-1] if flip[i] else f for i, f in enumerate(tris)])
    a, b, c = (p[tris] - wrist).transpose(1, 0, 2)
    return tris if (a * np.cross(b, c)).sum() > 0 else tris[:, ::-1]


def hand_colors(p, normal, pivots, unit, thumb_tip, thumb_pad):
    """Soft nail beds and the occlusion between adjacent finger roots."""
    rgb = np.ones((len(p), 3))
    across = nrm(pivots["Little1"] - pivots["Index1"])
    for name in DIGITS:
        axis = nrm(pivots[name + "3"] - pivots[name + "2"])
        origin = pivots[name + "3"]
        if name == "Thumb":
            axis = thumb_pad
            origin = thumb_tip - 0.023 * unit * axis
        wide = nrm(across - axis * (across @ axis))
        dorsal = nrm(np.cross(wide, axis))
        if dorsal[1] < 0:
            dorsal *= -1
        v = (p - origin) / unit
        # Two independent falloffs keep the nail on the dorsal distal pad.
        length = {"Little": 0.019, "Thumb": 0.023, "Middle": 0.024}.get(name, 0.022)
        ellipse = ((v @ axis - 0.64 * length) / (0.40 * length)) ** 2 + ((v @ wide) / 0.0078) ** 2
        nail = np.clip((1.35 - ellipse) * 3, 0, 1) * np.clip((normal @ dorsal - 0.30) * 2.5, 0, 1)
        rgb -= nail[:, None] * np.array([0.015, 0.16, 0.13])
    for a, b in zip(FINGERS, FINGERS[1:]):
        center = 0.5 * (pivots[a + "1"] + pivots[b + "1"])
        d = (p - center) / unit
        shade = np.exp(-np.sum(d * d, axis=1) / (0.013**2)) * (0.35 + 0.65 * np.abs(normal @ across))
        rgb -= shade[:, None] * np.array([0.07, 0.13, 0.14])
    return np.clip(rgb, 0, 1)


def fit(source, output, size):
    doc, buf = read_glb(source)
    # Immutable read buffer: glb.accessor returns views and we append new accessors.
    data = bytes(buf)

    def get(i):
        return glb.accessor(doc, data, i)

    def acc(v, typ, ct=5126):
        return append_accessor(
            doc, buf, array({5126: "f", 5123: "H"}[ct], np.asarray(v).ravel()), ct, typ, False
        )

    mesh = doc["meshes"][0]
    names = mesh["extras"]["targetNames"]
    mix = np.array(mesh["weights"])
    skin = doc["skins"][0]
    joints = skin["joints"]
    bones = [doc["nodes"][i]["name"] for i in joints]
    ibm = get(skin["inverseBindMatrices"]).reshape(-1, 4, 4).copy()
    frames = np.linalg.inv(ibm.transpose(0, 2, 1).astype(float))
    prim = next(p for p in mesh["primitives"] if p["material"] == 0)
    if "handTriangles" in prim.get("extras", {}):
        raise ValueError("hands already fitted; use the head checkpoint as input")
    at = prim["attributes"]
    pos = get(at["POSITION"])
    target = np.array([get(t["POSITION"]) for t in prim["targets"]])
    j, w = get(at["JOINTS_0"]), get(at["WEIGHTS_0"])
    tri = get(prim["indices"]).reshape(-1, 3)
    digits = [f + str(i) for f in DIGITS for i in (1, 2, 3)]
    in_hand = np.isin(np.array([n.split("_")[-1] for n in bones])[j], ["Hand", *digits])
    distal = ((w * in_hand).sum(1)[tri] >= 0.49).all(1)
    assert distal.any(), "input must carry the foundation's placeholder hands"
    boundary = edge_set(tri[distal]) & edge_set(tri[~distal])
    kept, indices = np.unique(tri[~distal], return_inverse=True)
    indices = indices.reshape(-1, 3)
    attributes = {name: [get(index)[kept]] for name, index in at.items()}
    colors = [np.ones((len(kept), 3))]
    shapes = [{name: [get(index)[kept]] for name, index in t.items()} for t in prim["targets"]]
    triangles_by_side = {}
    tips_by_side = {}
    indices = [indices]
    offset = len(kept)
    landmarks = np.unique(list(boundary))
    assert len(landmarks) in (40, 80)
    near = len(landmarks) == 80
    person_sizes = np.array(
        [MORPHS[n].get("hand", 1) * (0.82 if n == "Age_Child" else 1) - 1 for n in names]
    )
    person = 1 + mix @ person_sizes
    bind_ratio = size * person / (1 - 0.18 * mix[names.index("Age_Child")])
    for side in "LR":
        prefix = "J_Bip_" + side + "_"
        hand = bones.index(prefix + "Hand")
        wrist = frames[hand, :3, 3].copy()
        prefix_node = doc["nodes"][joints[hand]]
        prefix_node["scale"] = (bind_ratio * np.array(prefix_node.get("scale", [1, 1, 1]))).tolist()
        for bone in ["Hand", *digits]:
            m = frames[bones.index(prefix + bone)]
            m[:3, :3] *= bind_ratio
            m[:3, 3] = wrist + bind_ratio * (m[:3, 3] - wrist)
            ibm[bones.index(prefix + bone)] = np.linalg.inv(m).T
        # Set the metacarpal reach and the proximal phalanx breadth in
        # joint-local coordinates. Preserve the parent's animation path and
        # rebuild inverse binds through the distal phalanx.
        parent_i = hand
        original_parent = frames[hand].copy()
        # Allow more spread on the shorter child hand and more opposition on
        # the broad adult male hand, maintaining the grip aperture in metres.
        spread = 0.435 + 0.215 * mix[names.index("Age_Child")] - 0.014 * mix[names.index("Sex_Male")]
        thumb_scales = ((1.53, 0.86, spread), (1.14, 0.91, 0.84), (1.0, 1.0, 1.0))
        for number, scale in enumerate(thumb_scales, 1):
            index = bones.index(prefix + "Thumb" + str(number))
            node = doc["nodes"][joints[index]]
            if number < 3:
                node["scale"] = (np.array(node.get("scale", [1] * 3)) * scale).tolist()
            local = np.linalg.solve(original_parent, frames[index])
            original_parent = frames[index].copy()
            frames[index] = frames[parent_i] @ local @ np.diag([*scale, 1])
            ibm[index] = np.linalg.inv(frames[index]).T
            parent_i = index
        pivots = {bone: frames[bones.index(prefix + bone), :3, 3] for bone in ["Hand", *digits]}
        verts, weight_maps, faces, rim, tips, thumb_pad = hand_cage(pivots, size * person)
        dense = np.zeros((len(verts), len(bones)))
        for i, wm in enumerate(weight_maps):
            for name, weight in wm.items():
                dense[i, bones.index(prefix + name)] = weight
        combined = np.column_stack((verts, dense))
        if near:
            combined, faces, rim = subdivide(combined, faces, rim)
        verts, dense = combined[:, :3], combined[:, 3:]
        source_ids = landmarks[np.sign(pos[landmarks, 0]) == np.sign(wrist[0])]
        ids = np.arange(len(verts), len(verts) + len(source_ids))
        rest = pos[source_ids] + np.einsum("k,kij->ij", mix, target[:, source_ids])
        # The elder's arm cage follows the forward thorax. Carry the actual
        # forearm centre into the heel of the palm and ease back to the finger
        # pivots by the knuckles. A one-ring lateral correction kinks the wrist.
        palm_length = np.linalg.norm(pivots["Middle1"] - wrist)
        t = np.clip((np.linalg.norm(verts - wrist, axis=1) / palm_length - 0.14) / 0.86, 0, 1)
        heel = (1 - t * t * (3 - 2 * t))[:, None]
        verts = verts + heel * (rest.mean(0) - wrist)
        p = np.vstack([verts, rest])
        triangles = [t for a, b, c, d in faces for t in ((a, b, c), (a, c, d))]
        triangles += stitch(ids, rim, p)
        triangles = orient(triangles, p, wrist)
        # Seam vertices reproduce the arm's exact skin and morph data on both sides.
        assert {
            tuple(sorted((source_ids[a - ids[0]], source_ids[b - ids[0]])))
            for a, b in edge_set(triangles)
            if a >= ids[0] and b >= ids[0]
        } == {edge for edge in boundary if edge[0] in source_ids}
        js = np.argsort(-dense, axis=1)[:, :4]
        ws = np.take_along_axis(dense, js, axis=1)
        ws /= ws.sum(1)[:, None]
        a, b, c = p[triangles].transpose(1, 0, 2)
        normal = np.zeros_like(p)
        for ii in triangles.T:
            np.add.at(normal, ii, np.cross(b - a, c - a))
        normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-12)
        colors_hand = hand_colors(
            verts, normal[: len(verts)], pivots, size * person, verts[tips["Thumb"]], thumb_pad
        )
        deltas = [
            target[k, source_ids].mean(0) + (verts - wrist) * (s / person)
            for k, s in enumerate(person_sizes)
        ]
        basis = verts - np.einsum("k,kij->ij", mix, deltas)
        # Reuse forearm indices at the seam (including their normals and deltas)
        # and omit the unused stations inside the thumb opening.
        used = np.unique(triangles[triangles < len(verts)])
        remap = np.empty(len(p), dtype=int)
        remap[used] = offset + np.arange(len(used))
        remap[ids] = np.searchsorted(kept, source_ids)
        tips_by_side[side] = {name: int(remap[index]) for name, index in tips.items()}
        indices.append(remap[triangles])
        triangles_by_side[side] = len(triangles)
        offset += len(used)
        colors.append(colors_hand[used])
        for name, values in (
            ("POSITION", basis),
            ("NORMAL", normal),
            ("JOINTS_0", js),
            ("WEIGHTS_0", ws),
        ):
            attributes[name].append(values[used])
        for k, d in enumerate(deltas):
            shapes[k]["POSITION"].append(d[used])
            shapes[k]["NORMAL"].append(np.zeros((len(used), 3)))
    for name, parts in attributes.items():
        src = doc["accessors"][at[name]]
        at[name] = acc(np.vstack(parts), src["type"], src["componentType"])
    at["COLOR_0"] = acc(np.vstack(colors), "VEC3")
    for t, parts in zip(prim["targets"], shapes):
        for name, values in parts.items():
            t[name] = acc(np.vstack(values), "VEC3")
    prim["indices"] = acc(np.vstack(indices), "SCALAR", 5123)
    prim["extras"] = {
        "handTriangles": triangles_by_side,
        "handLinearScale": size,
        "handTips": tips_by_side,
    }
    skin["inverseBindMatrices"] = acc(ibm, "MAT4")
    output.parent.mkdir(exist_ok=True, parents=True)
    write_glb(output, doc, buf)
    shutil.copyfile(source.with_suffix(".face.png"), output.with_suffix(".face.png"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--size", type=float, default=1.135, help="linear scale over the fitted natural hand"
    )
    args = parser.parse_args()
    if not 0.5 <= args.size <= 1.5 or args.source.resolve() == args.output.resolve():
        parser.error("use separate files and a size between 0.5 and 1.5")
    fit(args.source, args.output, args.size)
