"""Run in Blender from the repo root after generating the types and styles in fittings.json."""
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

import numpy as np
from mathutils.bvhtree import BVHTree

sys.path[:0] = ["living/tools/characters", "living/tools"]
from merge_primitives import read_accessor, read_glb
from person_check import shaped

HERE = Path(__file__).resolve().parent
LOOKDEV = Path("living/game/assets/lookdev")


def tree(vertices, triangles):
    return BVHTree.FromPolygons(vertices.tolist(), triangles.tolist(), all_triangles=True)


def measure(body, line, tmp):
    target = tmp / f"{body}.glb"
    params = tmp / f"{body}.json"
    params.write_text(json.dumps({"person": line}))
    subprocess.run(["python3", "living/tools/characters/compose.py", LOOKDEV / "types" / (line["type"] + ".glb"),
                    target, "--person", params, "--drop", "Far"], check=True)
    details = {}
    head = shaped(target, lambda mesh, mat: mesh == "Face" and mat.endswith("_SKIN"), line["proportions"], details)
    scalp = tree(head, details["triangles"])
    joints = details["joints"]
    roots = [key for key in joints if key.startswith("J_Sec_Hair") and key.endswith("_01")]
    # The plait is built after the gathered crown and fringe.
    root = max(roots, key=lambda name: int(name.split("Hair")[1].split("_")[0]))
    root_mm = scalp.find_nearest(joints[root])[3] * 1000

    doc, data = read_glb(target)
    node = next(n for n in doc["nodes"] if n.get("name") == "Hair" and "mesh" in n)
    prefix = root.rsplit("_", 1)[0] + "_"
    chain = np.array([doc["nodes"][j]["name"].startswith(prefix) for j in doc["skins"][node["skin"]]["joints"]])
    mask = []
    for primitive in doc["meshes"][node["mesh"]]["primitives"]:
        attrs = primitive["attributes"]
        indices = np.array(read_accessor(doc, data, attrs["JOINTS_0"])[0]).reshape(-1, 4)
        weights = np.array(read_accessor(doc, data, attrs["WEIGHTS_0"])[0]).reshape(-1, 4)
        mask.extend((chain[indices] * weights).sum(axis=1) > .01)

    hair = shaped(target, lambda mesh, mat: mesh == "Hair", line["proportions"], details)
    ht = details["triangles"]
    braid = tree(hair, ht[np.asarray(mask)[ht].all(axis=1)])
    cloth = shaped(target, lambda mesh, mat: mesh == "Cloth", line["proportions"], details)
    ct = details["triangles"]
    centres = cloth[ct].mean(axis=1)
    collar = tree(cloth, ct[(centres[:, 1] > joints["J_Bip_C_UpperChest"][1]) &
                            (centres[:, 2] > joints["J_Bip_C_Neck"][2])])
    row = dict(body=body, root_joint=root, root_scalp_mm_in_rig_space=round(root_mm, 3),
               braid_triangles_intersecting_upper_back_and_collar=len({i for i, _ in braid.overlap(collar)}))
    hair_tree = tree(hair, ht)
    for side, name in (("L", "left"), ("R", "right")):
        ear = joints["J_Id_Ear_" + side]
        outward = np.array([np.sign(ear[0]), 0, 0])
        origins = [ear + .25 * outward + [0, dy, 0] for dy in (-.008, 0, .008)]
        row[name + "_ear_landmark_rays_open_of_3"] = sum(
            hair_tree.ray_cast(origin, -outward, .25)[0] is None for origin in origins)
    return row


with TemporaryDirectory() as directory:
    lines = json.loads((HERE / "fittings.json").read_text())
    rows = [measure(body, params["port"], Path(directory)) for body, params in lines.items()]
print(json.dumps(rows, indent=2))
