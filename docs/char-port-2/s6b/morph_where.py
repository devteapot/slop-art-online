"""Where an expression's new crossings are: pairs of crossing skin triangles at full weight that do not cross at rest, their centres."""
import sys, numpy as np
from mathutils.bvhtree import BVHTree
sys.path[:0]=["living/tools"]
from merge_primitives import read_glb, read_accessor
argv=sys.argv[sys.argv.index("--")+1:]; f, key = argv[0], argv[1]
arr=lambda j,b,i: np.array(read_accessor(j,b,i)[0], float)
j,b=read_glb(f); node=next(n for n in j["nodes"] if n.get("name")=="Face" and "mesh" in n); mesh=j["meshes"][node["mesh"]]; names=mesh["extras"]["targetNames"]
for p in mesh["primitives"]:
    if not j["materials"][p["material"]]["name"].endswith("Face_00_SKIN"): continue
    P=arr(j,b,p["attributes"]["POSITION"]).reshape(-1,3); T=arr(j,b,p["indices"]).reshape(-1,3).astype(int)
    D=arr(j,b,p["targets"][names.index(key)]["POSITION"]).reshape(-1,3)
    def pairs(V):
        t=BVHTree.FromPolygons(V.tolist(), T.tolist(), all_triangles=True)
        return {(a,c) for a,c in t.overlap(t) if a<c and not (set(T[a])&set(T[c]))}
    new=pairs(P+D)-pairs(P)
    I=next(arr(j,b,q["attributes"]["POSITION"]).reshape(-1,3) for q in mesh["primitives"] if "EyeIris" in j["materials"][q["material"]]["name"])
    eye=I.mean(0)
    for a,c in sorted(new)[:30]:
        ca=(P+D)[T[a]].mean(0)-eye; cc=(P+D)[T[c]].mean(0)-eye
        print("x %+.1f y %+.1f z %+.1f mm | x %+.1f y %+.1f z %+.1f mm" % (*(ca*1000), *(cc*1000)))
    print(len(new), "new pairs")
