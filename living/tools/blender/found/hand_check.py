"""Check a fitted hand pair against its input and measure the animated right grip."""

import argparse
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

import numpy as np

from hands import DIGITS, TOOLS, fit, glb

sys.path.insert(0, str(TOOLS / "characters"))
from cloth_check import quat


def measure(path):
    doc, binary, _ = glb.read(path)

    def get(i):
        return glb.accessor(doc, binary, i)

    mesh, face = doc["meshes"]
    p = next(p for p in mesh["primitives"] if "handTriangles" in p.get("extras", {}))
    at = p["attributes"]
    pos = get(at["POSITION"]).copy()
    for w, t in zip(mesh["weights"], p["targets"]):
        pos += w * get(t["POSITION"])
    j = get(at["JOINTS_0"])
    w = get(at["WEIGHTS_0"])
    nodes = doc["nodes"]
    skin = doc["skins"][0]
    ids = skin["joints"]
    names = [nodes[i]["name"] for i in ids]
    ibm = get(skin["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1)
    pivots = np.linalg.inv(ibm)[:, :3, 3]
    root = doc["scenes"][0]["nodes"][0]
    factor = nodes[root]["scale"][0]

    def joint(name):
        return names.index("J_Bip_R_" + name)

    # Follow the distal cap selected in bind, including the blended identity shape.
    tips = []
    for digit in DIGITS:
        bone = joint(digit + "3")
        verts = np.flatnonzero((w * (j == bone)).sum(1) > 0.8)
        axis = pivots[bone] - pivots[joint(digit + "2")]
        tips.append(verts[np.argmax(pos[verts] @ axis)])
    span = np.linalg.norm(pos[tips[1]] - pivots[joint("Hand")]) * factor
    index_bones = [joint("Index" + str(i)) for i in range(1, 4)]
    index_skin = np.flatnonzero((w * np.isin(j, index_bones)).sum(1) > 0.6)
    sel = np.r_[tips, index_skin]
    hom = np.column_stack((pos[sel], np.ones(len(sel))))
    stats = {}
    for clip, time in (("idle", 1.0), ("wave", 1.0), ("sword_slash", 16 / 30), ("sword_overhead", 0.6)):
        anim = next(a for a in doc["animations"] if a["name"] == clip)
        pose = {}
        for c in anim["channels"]:
            target = c["target"]
            samp = anim["samplers"][c["sampler"]]
            times = get(samp["input"]).ravel()
            frame = int(np.abs(times - time).argmin())
            pose[target["node"], target["path"]] = get(samp["output"])[frame]
        frames = {}

        def visit(i, parent):
            node = nodes[i]
            loc = np.eye(4)
            loc[:3, :3] = quat(pose.get((i, "rotation"), node.get("rotation", [0, 0, 0, 1]))) * node.get(
                "scale", [1] * 3
            )
            loc[:3, 3] = pose.get((i, "translation"), node.get("translation", [0] * 3))
            frames[i] = parent @ loc
            for child in node.get("children", []):
                visit(child, frames[i])

        visit(root, np.eye(4))
        mat = np.array([frames[i] for i in ids]) @ ibm
        deformed = np.einsum("vk,vkij,vj->vi", w[sel], mat[j[sel]], hom)[:, :3]
        palm = 0.5 * (frames[ids[joint("Hand")]][:3, 3] + frames[ids[joint("Middle1")]][:3, 3])
        stats[clip] = {
            "seconds": round(time, 4),
            "thumb3_to_index3_pivots_mm": round(
                1000
                * np.linalg.norm(
                    frames[ids[joint("Thumb3")]][:3, 3] - frames[ids[joint("Index3")]][:3, 3]
                ),
                2,
            ),
            "tip_to_palm_mm": dict(
                zip(DIGITS, np.round(1000 * np.linalg.norm(deformed[:5] - palm, axis=1), 2))
            ),
            "thumb_tip_to_index_skin_mm": round(
                1000 * np.linalg.norm(deformed[5:] - deformed[4], axis=1).min(), 2
            ),
        }
    tris = lambda mesh: sum(doc["accessors"][p["indices"]]["count"] // 3 for p in mesh["primitives"])
    hands = sum(p["extras"]["handTriangles"].values())
    counts = {"body": tris(mesh) - hands, "hands": hands, "head": tris(face), "hair": 0}
    return counts, float(span), stats


def wrist_edges(doc, binary):
    prim = next(p for p in doc["meshes"][0]["primitives"] if "handTriangles" in p.get("extras", {}))
    tri = glb.accessor(doc, binary, prim["indices"]).reshape(-1, 3)
    counts = prim["extras"]["handTriangles"]
    first = len(tri) - sum(counts.values())

    def directed(triangles):
        return Counter(
            map(
                tuple, np.concatenate([triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]])
            )
        )

    arm = directed(tri[:first])
    widths = {}
    for side in "LR":
        part = tri[first : first + counts[side]]
        edges = directed(part)
        assert max(edges.values()) == 1
        border = [(a, b) for a, b in edges if (b, a) not in edges]
        assert len(border) in (20, 40) and all(arm[b, a] == 1 for a, b in border)
        # A connected hand has one boundary and the Euler characteristic of a disk.
        undirected = (len(edges) + len(border)) // 2
        assert len(np.unique(part)) - undirected + len(part) == 1
        widths[side] = len(border)
        first += len(part)
    return widths


def check(source, output):
    before, original, _ = glb.read(source)
    doc, binary, _ = glb.read(output)
    assert binary.startswith(original)
    for k in ("animations", "materials", "textures", "images", "extensions"):
        assert doc[k] == before[k], k
    assert doc["meshes"][1:] == before["meshes"][1:]
    assert source.with_suffix(".face.png").read_bytes() == output.with_suffix(".face.png").read_bytes()
    skin = doc["skins"][0]
    ids = skin["joints"]
    assert ids == before["skins"][0]["joints"] and len(ids) == 82
    for n, old in zip(doc["nodes"], before["nodes"], strict=True):
        if n["name"] in ("J_Bip_L_Hand", "J_Bip_R_Hand"):
            assert {k: v for k, v in n.items() if k != "scale"} == {
                k: v for k, v in old.items() if k != "scale"
            }
        else:
            assert n == old
    counts, span, stats = measure(output)
    with tempfile.TemporaryDirectory() as directory:
        natural = Path(directory) / "natural.glb"
        fit(source, natural, 1.0)
        _, reference, _ = measure(natural)
    report = {
        "triangles": counts,
        "welded_wrist_edges": wrist_edges(doc, binary),
        "rest_wrist_to_middle_tip_mm": round(1000 * span, 2),
        "natural_wrist_to_middle_tip_mm": round(1000 * reference, 2),
        "size_ratio": round(span / reference, 5),
        "right_hand": stats,
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    check(a.source, a.output)
