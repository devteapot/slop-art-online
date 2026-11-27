"""Fit the project-owned Cora face and its expression topology to a generated foundation GLB."""

import argparse
import shutil
import sys
from array import array
from pathlib import Path

import numpy as np

TOOLS = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(TOOLS), str(TOOLS / "board")]
import glb
from merge_primitives import append_accessor, read_glb, write_glb

MASTER = TOOLS.parents[1] / "docs/char-live-2/final/own-cora-live.glb"


def portrait(points, name):
    """Warp the complete socket, eyeball, iris and lid assembly in the same field."""
    x, y, z = points.T
    eye = np.exp(-(((abs(x) - 0.032) / 0.031) ** 4) - ((y - 1.519) / 0.027) ** 4)
    cheek = np.exp(-(((y - 1.483) / 0.027) ** 2))
    jaw = np.exp(-(((y - 1.459) / 0.028) ** 2))
    brow = np.exp(-(((y - 1.542) / 0.014) ** 2))
    front = np.clip((z - 0.016) / 0.04, 0, 1)
    width, length, orbit, ridge, hollow = {
        "Sex_Male": (0.19, 0.06, -0.15, 0.007, -0.001),
        "Sex_Female": (-0.10, -0.02, 0.10, -0.002, 0.002),
        "Age_Child": (0.19, -0.19, 0.39, -0.004, 0.005),
        "Age_Elder": (-0.09, 0.08, -0.28, 0.003, -0.010),
        "Face_Round": (0.21, -0.09, 0.04, 0, 0.004),
        "Face_Long": (-0.11, 0.18, 0, 0, -0.002),
        "Jaw_Square": (0.24, 0.02, 0, 0.003, 0),
    }.get(name, (0, 0, 0, 0, 0))
    a = points.copy()
    # Cora's jaw was fitted under her side locks. Ease its lateral corner
    # into the mandibular angle before applying the individual shapes.
    lateral = np.clip((abs(x) - 0.025) / 0.028, 0, 1)
    angle = np.exp(-(((y - 1.465) / 0.023) ** 2)) * lateral
    rear = np.clip((0.058 - z) / 0.048, 0, 1)
    a[:, 1] += 0.010 * angle * rear
    a[:, 0] -= 0.005 * np.sign(x) * angle * rear
    a[:, 0] += x * width * (0.75 * jaw + 0.45 * cheek) * (
        0.18 + 0.82 * front
    ) + orbit * eye * (x - np.sign(x) * 0.032)
    a[:, 1] += length * (y - 1.52) * np.clip((1.54 - y) / 0.075, 0, 1) + orbit * eye * (
        y - 1.519
    )
    a[:, 2] += front * (ridge * brow + hollow * cheek)
    if name == "Age_Elder":
        a[:, 1] -= front * (0.005 * cheek + 0.0025 * brow)
        a[:, 2] += front * (
            0.006 * np.exp(-((x / 0.019) ** 2) - ((y - 1.494) / 0.018) ** 2)
            - 0.005
            * np.exp(-(((abs(x) - 0.038) / 0.016) ** 2) - ((y - 1.513) / 0.013) ** 2)
        )
    if name == "Sex_Male":
        a[:, 2] += front * (
            0.005 * np.exp(-((x / 0.022) ** 2) - ((y - 1.485) / 0.022) ** 2)
            + 0.005 * jaw
        )

    return a


def fit(source, output, expression=None):
    doc, buf = read_glb(source)
    master, data, _ = glb.read(MASTER)
    body = doc["meshes"][0]
    names = body["extras"]["targetNames"]
    mix = body["weights"]
    src_face = master["meshes"][1]
    expressions = src_face["extras"]["targetNames"]
    joints = [doc["nodes"][i]["name"] for i in doc["skins"][0]["joints"]]
    index = joints.index("J_Bip_C_Head")

    def acc(v, typ, ct=5126):
        return append_accessor(
            doc,
            buf,
            array({5126: "f", 5123: "H"}[ct], np.asarray(v).ravel()),
            ct,
            typ,
            False,
        )

    # Measure the old crown and chin for each shape before removing the placeholder.
    samples = [[] for _ in range(len(names) + 1)]
    remaining = []
    for prim in body["primitives"]:
        at = prim["attributes"]
        pos = glb.accessor(doc, buf, at["POSITION"]).copy()
        ids = glb.accessor(doc, buf, at["JOINTS_0"]).copy()
        wt = glb.accessor(doc, buf, at["WEIGHTS_0"]).copy()
        head = ids[np.arange(len(pos)), wt.argmax(1)] == index
        if head.any():
            samples[0].append(pos[head])
            for i, t in enumerate(prim["targets"]):
                samples[i + 1].append(
                    pos[head] + glb.accessor(doc, buf, t["POSITION"])[head]
                )
            tris = glb.accessor(doc, buf, prim["indices"]).reshape(-1, 3).copy()
            removed = head[tris].all(1)
            kept = tris[~removed]
            if not len(kept):
                continue
            if prim["material"] == 0:

                def edge_set(faces):
                    return {
                        tuple(sorted((a, b)))
                        for tri in faces
                        for a, b in zip(tri, np.roll(tri, -1))
                    }

                lower_ids = np.unique(list(edge_set(kept) & edge_set(tris[removed])))
                lower = prim
            prim["indices"] = acc(kept, "SCALAR", 5123)
        remaining.append(prim)
    body["primitives"] = remaining
    bounds = []
    for sample in samples:
        v = np.concatenate(sample)
        bounds.append((v.min(0), v.max(0)))

    def shape(v, i):
        lo, hi = bounds[i]
        # The master faces +Z. Foundation is built facing -Z and the scene supplies the game yaw.
        v = portrait(v, names[i - 1] if i else "")
        u = (v - [0, 1.43039, 0.014]) * [-1, 1, -1]
        # Keep the chin on its fitting landmark as the lower face gets shorter.
        chin = portrait(np.array([[0.0, 1.43039, 0.078]]), names[i - 1] if i else "")[
            0, 1
        ]
        u[:, 1] = (v[:, 1] - chin) * 0.20015 / (1.63054 - chin)
        size = hi - lo
        return u * [size[0] / 0.152, size[1] / 0.20015, size[2] / 0.1954] + [
            (hi[0] + lo[0]) / 2,
            lo[1],
            (hi[2] + lo[2]) / 2,
        ]

    for image in master["images"]:
        view = master["bufferViews"][image["bufferView"]]
        start = view.get("byteOffset", 0)
        while len(buf) % 4:
            buf.append(0)
        image["bufferView"] = len(doc["bufferViews"])
        doc["bufferViews"].append(
            {"buffer": 0, "byteOffset": len(buf), "byteLength": view["byteLength"]}
        )
        buf.extend(data[start : start + view["byteLength"]])
    for k in ("images", "textures", "samplers"):
        doc[k] = master[k]
    primitives = []
    for p in src_face["primitives"]:
        at = p["attributes"]
        v = glb.accessor(master, data, at["POSITION"]).astype(float)
        base = shape(v, 0)
        n = glb.accessor(master, data, at["NORMAL"]) * [-1, 1, -1]
        attrs = {"POSITION": acc(base, "VEC3"), "NORMAL": acc(n, "VEC3")}
        for key in ("TEXCOORD_0", "TEXCOORD_1", "COLOR_0"):
            a = at[key]
            attrs[key] = acc(
                glb.accessor(master, data, a), master["accessors"][a]["type"]
            )
        attrs["JOINTS_0"] = acc(np.tile([index, 0, 0, 0], (len(v), 1)), "VEC4", 5123)
        attrs["WEIGHTS_0"] = acc(np.tile([1, 0, 0, 0], (len(v), 1)), "VEC4")
        attrs["_OUTLINE_WIDTH"] = acc(np.full(len(v), 0.4), "SCALAR")
        target = [
            {"POSITION": acc(shape(v, i + 1) - base, "VEC3")} for i in range(len(names))
        ]
        for t in p["targets"]:
            dv = glb.accessor(master, data, t["POSITION"])
            delta = shape(v + dv, 0) - base
            for i, w in enumerate(mix):
                if w:
                    delta += w * (
                        shape(v + dv, i + 1)
                        - shape(v, i + 1)
                        - (shape(v + dv, 0) - base)
                    )
            target.append({"POSITION": acc(delta, "VEC3")})
        mat = len(doc["materials"])
        doc["materials"].append(master["materials"][p["material"]])
        primitives.append(
            {
                "attributes": attrs,
                "material": mat,
                "indices": acc(
                    glb.accessor(master, data, p["indices"]), "SCALAR", 5123
                ),
                "targets": target,
            }
        )
    # Cora's calibrated jaw underside ends at a 56-station cervical opening.
    # Zip its actual vertices to the exposed foundation ring, retaining the
    # independent skin weights and expression deltas on either edge.
    face_skin = primitives[0]
    src = src_face["primitives"][0]
    raw = glb.accessor(master, data, src["attributes"]["POSITION"])
    unique, original, inverse = np.unique(
        raw.round(5), axis=0, return_index=True, return_inverse=True
    )
    tri = inverse[glb.accessor(master, data, src["indices"]).reshape(-1, 3)]
    edges = np.sort(
        np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]]), axis=1
    )
    edge, count = np.unique(edges, axis=0, return_counts=True)
    boundary = np.unique(edge[count == 1])
    x, y, z = unique[boundary].T
    upper_ids = original[
        boundary[(abs(x) < 0.032) & (y >= 1.4559) & (y <= 1.4661) & (z < 0.043)]
    ]
    assert len(upper_ids) == 56

    def order(prim, ids):
        xyz = glb.accessor(doc, buf, prim["attributes"]["POSITION"])[ids]
        centre = xyz.mean(0)
        angles = np.mod(
            np.arctan2(xyz[:, 2] - centre[2], xyz[:, 0] - centre[0]), 2 * np.pi
        )
        return ids[np.argsort(angles)]

    low = order(lower, lower_ids)
    high = order(face_skin, upper_ids)
    bottom, top = len(low), len(high)
    triangles = []
    i = j = 0
    while i < bottom or j < top:
        a = i % bottom
        b = bottom + j % top
        if i < bottom and (j == top or (i + 1) * top <= (j + 1) * bottom):
            triangles.append((a, b, (i + 1) % bottom))
            i += 1
        else:
            triangles.append((a, b, bottom + (j + 1) % top))
            j += 1

    def joined(field):
        return np.vstack(
            [
                glb.accessor(doc, buf, pr["attributes"][field])[ids]
                for pr, ids in ((lower, low), (face_skin, high))
            ]
        )

    attrs = {
        key: acc(joined(key), typ, ct)
        for key, typ, ct in [
            ("POSITION", "VEC3", 5126),
            ("NORMAL", "VEC3", 5126),
            ("JOINTS_0", "VEC4", 5123),
            ("WEIGHTS_0", "VEC4", 5126),
        ]
    }
    attrs["_OUTLINE_WIDTH"] = acc(np.r_[np.ones(bottom), np.full(top, 0.4)], "SCALAR")
    shapes = []
    for i, t in enumerate(face_skin["targets"]):
        l = (
            glb.accessor(doc, buf, lower["targets"][i]["POSITION"])[low]
            if i < len(names)
            else np.zeros((bottom, 3))
        )
        h = glb.accessor(doc, buf, t["POSITION"])[high]
        shapes.append({"POSITION": acc(np.vstack([l, h]), "VEC3")})
    primitives.append(
        {
            "attributes": attrs,
            "material": 0,
            "indices": acc(triangles, "SCALAR", 5123),
            "targets": shapes,
        }
    )
    doc["meshes"].append(
        {
            "name": "Foundation face",
            "primitives": primitives,
            "weights": mix + [float(n == expression) for n in expressions],
            "extras": {"targetNames": names + expressions},
        }
    )
    root = doc["scenes"][0]["nodes"][0]
    doc["nodes"][root].pop(
        "rotation", None
    )  # VRM 0.x supplies the scene yaw in the viewer.
    doc["nodes"][root]["children"].append(len(doc["nodes"]))
    doc["nodes"].append({"name": "Face", "mesh": 1, "skin": 0})
    presets = {
        "Fcl_EYE_Close": "blink",
        "Fcl_EYE_Close_L": "blink_l",
        "Fcl_EYE_Close_R": "blink_r",
        **{"Fcl_MTH_" + v: v.lower() for v in "AIUEO"},
        "Fcl_EYE_Joy": "joy",
        "Fcl_MTH_Fun": "fun",
        "Fcl_BRW_Angry": "angry",
        "Fcl_BRW_Sorrow": "sorrow",
    }
    groups = [
        {
            "name": n,
            "presetName": presets.get(n, "unknown"),
            "binds": [{"mesh": 1, "index": len(names) + i, "weight": 100}],
            "materialValues": [],
            "isBinary": False,
        }
        for i, n in enumerate(expressions)
    ]
    mapping = {}
    for bone in ("Hips", "Spine", "Chest", "UpperChest", "Neck", "Head"):
        mapping[bone[0].lower() + bone[1:]] = "J_Bip_C_" + bone
    for side, prefix in (("L", "left"), ("R", "right")):
        for bone in (
            "Shoulder",
            "UpperArm",
            "LowerArm",
            "Hand",
            "UpperLeg",
            "LowerLeg",
            "Foot",
            "ToeBase",
        ):
            mapping[prefix + ("Toes" if bone == "ToeBase" else bone)] = (
                "J_Bip_" + side + "_" + bone
            )
        for digit in ("Thumb", "Index", "Middle", "Ring", "Little"):
            for joint, suffix in enumerate(("Proximal", "Intermediate", "Distal"), 1):
                mapping[prefix + digit + suffix] = f"J_Bip_{side}_{digit}{joint}"
    nodes = {n["name"]: i for i, n in enumerate(doc["nodes"]) if "name" in n}
    humanoid = [
        {"bone": k, "node": nodes[v], "useDefaultValues": True}
        for k, v in mapping.items()
    ]
    doc.setdefault("extensions", {})["VRM"] = {
        "specVersion": "0.0",
        "exporterVersion": "Slop Art Online foundation",
        "meta": {
            "title": output.stem,
            "author": "Slop Art Online",
            "licenseName": "Other",
        },
        "humanoid": {"humanBones": humanoid},
        "firstPerson": {
            "firstPersonBone": nodes["J_Bip_C_Head"],
            "meshAnnotations": [],
        },
        "blendShapeMaster": {"blendShapeGroups": groups},
    }
    doc["extensionsUsed"] = list(
        dict.fromkeys(
            doc.get("extensionsUsed", []) + master["extensionsUsed"] + ["VRM"]
        )
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    write_glb(output, doc, buf)
    shutil.copyfile(MASTER.with_suffix(".face.png"), output.with_suffix(".face.png"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("body", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--expression")
    a = parser.parse_args()
    fit(a.body, a.output, a.expression)
