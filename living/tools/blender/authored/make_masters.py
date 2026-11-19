"""Rebuild the editable Blender source files and their named secondary rig from the authored cuts.
BLENDER=$HOME/.local/share/slop-tools/build-bin/blender python3 make_masters.py
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parents[1]))
from merge_primitives import read_glb
from rig_data import rebind

def main():
    blender=os.environ["BLENDER"]
    cuts={
        "head":["--variant","type:adult-f-a","--parts","head","--morphs","client"],
        "hair":["--variant","style:long","--parts","hair"],
        "outfit":["--variant","piece:smock_58-f","--parts","keep","--keep","Smock"],
    }
    springs={}
    with tempfile.TemporaryDirectory() as tmp:
        for name,args in cuts.items():
            glb=Path(tmp)/("adult-f-a.glb" if name=="head" else name+".glb")
            blend=HERE/(name+".blend")
            subprocess.run([blender,"-b","-t","2","--python-exit-code","1","-P",HERE.parent/"person.py","--",
                            "--atelier",*args,"--lod","both","--blend",blend,"--out",glb],check=True)
            j,_=read_glb(glb)
            springs[name]=rebind(j["extensions"]["VRM"]["secondaryAnimation"],
                                 {i:n.get("name") for i,n in enumerate(j["nodes"])})
        for script in ("body_form.py","finish_face.py"):
            subprocess.run([blender,"-b","-t","2","--python-exit-code","1","-P",HERE/script,"--",HERE/"head.blend"],check=True)
    (HERE/"springs.json").write_text(json.dumps(springs,indent=2)+"\n")

if __name__=="__main__":
    main()
