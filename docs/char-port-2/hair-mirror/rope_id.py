#!/usr/bin/env python3
"""rope_id.py WITH.glb OUT.glb: part_id.py --all, with the triangles skinned to the spring rope
(any vertex weighted to a J_Sec_* bone: the plait) in magenta, so a mirror check can leave out the
plait, which both builds of a mirrored pair share unmirrored."""
import copy, sys
from pathlib import Path
import numpy as np
W = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(W / "docs/char-port-2/s6"), str(W / "living/tools")]
from merge_primitives import read_glb, write_glb  # noqa
from plait_id import accessor  # noqa
from part_id import fixed, COLOURS  # noqa

j, binary = read_glb(sys.argv[1]); binary = bytearray(binary)
hair = next(i for i, m in enumerate(j["materials"]) if "_HAIR" in m.get("name", ""))
j["materials"][hair] = fixed(j["materials"][hair], j["materials"][hair]["name"], COLOURS[0])
j["materials"].append(fixed(j["materials"][hair], "ZZ_Rope_HAIR", COLOURS[1])); gid = len(j["materials"]) - 1
moved = 0
for node in j["nodes"]:
    if "mesh" not in node: continue
    names = [j["nodes"][i]["name"] for i in j["skins"][node["skin"]]["joints"]]
    sec = np.array([n.startswith("J_Sec_") for n in names])
    m = j["meshes"][node["mesh"]]; add = []
    for p in m["primitives"]:
        if p.get("material") != hair: continue
        jt = accessor(j, binary, p["attributes"]["JOINTS_0"]).astype(int); wt = accessor(j, binary, p["attributes"]["WEIGHTS_0"]).astype(float)
        rope_v = (sec[jt] & (wt > 0)).any(axis=1)
        idx = accessor(j, binary, p["indices"]).reshape(-1, 3).astype(np.uint32)
        mine = rope_v[idx].any(axis=1); moved += int(mine.sum())
        for sel, target in ((~mine, p), (mine, None)):
            data = idx[sel].astype(np.uint32).ravel().tobytes()
            while len(binary) % 4: binary.append(0)
            j["bufferViews"].append(dict(buffer=0, byteOffset=len(binary), byteLength=len(data), target=34963)); binary.extend(data)
            j["accessors"].append(dict(bufferView=len(j["bufferViews"]) - 1, componentType=5125, count=int(sel.sum()) * 3, type="SCALAR"))
            if target is not None: target["indices"] = len(j["accessors"]) - 1
            else:
                q = copy.deepcopy(p); q["indices"] = len(j["accessors"]) - 1; q["material"] = gid; add.append(q)
    m["primitives"] += add
j["buffers"][0]["byteLength"] = len(binary)
write_glb(sys.argv[2], j, binary)
print("rope_id:", moved, "rope triangles magenta")
