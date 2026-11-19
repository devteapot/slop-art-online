"""Count exported active vertices/indices, skin weights and material slots per Near/Far LOD."""
import json
from pathlib import Path
import sys
import numpy as np
from lineup import lines,TOOLS
sys.path.insert(0,str(TOOLS))
from merge_primitives import read_glb,read_accessor


def inspect(files):
    rows={}
    for path in files:
        j,b=read_glb(path)
        for mesh in j["meshes"]:
            lod="far" if mesh["name"].startswith("Far") else "near"
            row=rows.setdefault(lod,dict(vertices=0,triangles=0,primitives=0,materials=set(),zero_weight=0,
                                         max_weight_error=0.,max_influences=0))
            for p in mesh["primitives"]:
                a=p["attributes"]
                row["vertices"]+=j["accessors"][a["POSITION"]]["count"]
                row["triangles"]+=j["accessors"][p["indices"]]["count"]//3
                row["primitives"]+=1
                row["materials"].add(j["materials"][p["material"]]["name"])
                w,desc=read_accessor(j,b,a["WEIGHTS_0"])
                weights=np.asarray(w).reshape(-1,4).astype(float)
                if desc[2]:
                    weights/=255 if desc[0]==5121 else 65535
                totals=weights.sum(axis=1)
                row["zero_weight"]+=int(np.count_nonzero(totals==0))
                row["max_weight_error"]=max(row["max_weight_error"],float(np.abs(totals-1).max()))
                row["max_influences"]=max(row["max_influences"],int((weights>0).sum(axis=1).max()))
    for row in rows.values():
        row["materials"]=sorted(row["materials"])
    return rows


if __name__=="__main__":
    look=Path(sys.argv[1])
    records={}
    for r in lines(look):
        p=r["person"]
        files=[look/"types"/(p["type"]+".glb"),look/"styles/hair"/(p["styles"]["hair"]+".glb")]
        files += [look/"styles/outfit"/(n+".glb") for n in p["styles"]["outfit"]]
        records[r["name"]]=inspect(files)
    print(json.dumps(records,indent=2))
