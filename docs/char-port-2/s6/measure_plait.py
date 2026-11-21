"""char-port-1's braid checks on a master's plait (char-port-2 S6 step 3): the plait's root to the
scalp, the plait's triangles touching the coat's collar and upper back, and the ears' landmark
rays, on a woman of each female type wearing each cut of the master over a coat.

Run in Blender from the repo root, with the master's files installed in the asset tree:

    blender -b --python-exit-code 1 -P docs/char-port-2/s6/measure_plait.py -- OUT.json [STYLE [TYPES [CUTS]]]

STYLE is the master (default swept_braid). The women are residents of the island's look book (a
coated woman of each type, `living/game/assets/characters/looks.json`), each wearing `STYLE.collar`,
`STYLE.2.collar` and `STYLE.3.collar` in place of her own hair, and a coat, jersey, trousers and
boots. The measures are char-port-1's (docs/char-port-1/measure_braid.py), unchanged: the root is
the last spring chain the hair adds (the plait is built after everything else), the collar the
cloth above the upper chest's joint and the neck's, and the ears three lateral rays each.
"""
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

import numpy as np
from mathutils.bvhtree import BVHTree

sys.path[:0] = ["living/tools/characters", "living/tools"]
from merge_primitives import read_accessor, read_glb  # noqa: E402
from person_check import shaped  # noqa: E402

LOOKDEV = Path("living/game/assets/lookdev")
TYPES = ("adult-f-a", "adult-f-b", "adult-f-c", "elder-f-a", "elder-f-b", "elder-f-c", "youth-f-a", "youth-f-b", "youth-f-c")
OUTFIT = ["coat-f", "jersey_coat-f", "trousers-f", "boots-f"]


def tree(vertices, triangles):
    return BVHTree.FromPolygons(vertices.tolist(), triangles.tolist(), all_triangles=True)


def measure(line, tmp, name):
    target = tmp / f"{name}.glb"
    params = tmp / f"{name}.json"
    params.write_text(json.dumps({"person": line}))
    subprocess.run(["python3", "living/tools/characters/compose.py", LOOKDEV / "types" / (line["type"] + ".glb"), target, "--person", params, "--drop", "Far"],
                   check=True, stdout=subprocess.DEVNULL)
    details = {}
    head = shaped(target, lambda mesh, mat: mesh == "Face" and mat.endswith("_SKIN"), line["proportions"], details)
    scalp = tree(head, details["triangles"])
    joints = details["joints"]
    roots = [key for key in joints if key.startswith("J_Sec_Hair") and key.endswith("_01")]
    root = max(roots, key=lambda n: int(n.split("Hair")[1].split("_")[0]))
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
    braid_t = ht[np.asarray(mask)[ht].all(axis=1)]
    braid = tree(hair, braid_t)
    cloth = shaped(target, lambda mesh, mat: mesh == "Cloth", line["proportions"], details)
    ct = details["triangles"]
    centres = cloth[ct].mean(axis=1)
    collar = tree(cloth, ct[(centres[:, 1] > joints["J_Bip_C_UpperChest"][1]) & (centres[:, 2] > joints["J_Bip_C_Neck"][2])])
    row = dict(root_joint=root, plait_triangles=int(len(braid_t)), root_scalp_mm_in_rig_space=round(root_mm, 3),
               braid_triangles_intersecting_upper_back_and_collar=len({i for i, _ in braid.overlap(collar)}))
    hair_tree = tree(hair, ht)
    for side, nm in (("L", "left"), ("R", "right")):
        ear = joints["J_Id_Ear_" + side]
        outward = np.array([np.sign(ear[0]), 0, 0])
        origins = [ear + .25 * outward + [0, dy, 0] for dy in (-.008, 0, .008)]
        row[nm + "_ear_landmark_rays_open_of_3"] = sum(hair_tree.ray_cast(origin, -outward, .25)[0] is None for origin in origins)
    return row


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = Path(argv[0] if argv else "measure-plait.json")
    style = argv[1] if len(argv) > 1 else "swept_braid"
    types = argv[2].split(",") if len(argv) > 2 else TYPES  # a few types only (a quick look)
    cuts = argv[3].split(",") if len(argv) > 3 else ("", ".2", ".3")
    book = json.loads(Path("living/game/assets/characters/looks.json").read_text())["lines"]
    women = {}
    for key, v in sorted(book.items()):
        p = v["person"]
        if p["type"] in TYPES and p["type"] not in women and any(o.startswith("coat") for o in p["styles"]["outfit"]):
            women[p["type"]] = (key, p)
    rows = []
    with TemporaryDirectory() as d:
        for t in types:
            key, p = women[t]
            for cut in [c if c in ("", ".2", ".3") else "" for c in cuts]:
                line = json.loads(json.dumps(p))
                line["styles"] = dict(line["styles"], hair=f"{style}{cut}.collar", outfit=list(OUTFIT))
                line["colors"]["outfit"] = {k: v for k, v in line["colors"].get("outfit", {}).items() if k in OUTFIT}
                row = dict(type=t, resident=key, hair=line["styles"]["hair"])
                row.update(measure(line, Path(d), f"{t}{cut}"))
                rows.append(row)
                print(json.dumps(row), flush=True)
    out.write_text(json.dumps(rows, indent=1))


main()
