"""Write the controlled spike recipes to a separate book. Keep height, dyes and pose
matched between the primary pair. Other rows deliberately vary age, build and seed.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

TOOLS=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(TOOLS/"characters"))
import face_types

def lines(look):
    pieces=["smock_58-f","jersey_smock-f","smock_bands-f","trousers-f","boots-f"]
    palette=["#557283","#d8c5a1","#c29b65","#34404f","#4e3938"]
    cases=[("control",23,71,1.65,1),("atelier",23,71,1.65,1),
           ("atelier-youth",16,163,1.53,.93),("atelier-broad",34,294,1.74,1.12)]
    for name,age,seed,height,width in cases:
        kind=face_types.band_of(age)+"-f-a"
        hybrid=name!="control"
        face=face_types.load()["types"][kind]
        ident=face_types.draw_valid(face,seed)
        p=deepcopy(json.loads((look/"types"/(kind+".params.json")).read_text())["person"])
        styles=[("atelier-f" if i==0 else "atelier-"+style) if hybrid else style for i,style in enumerate(pieces)]
        p.update(type=("atelier-" if hybrid else "")+kind,height=height,identity=ident)
        p["styles"]={"hair":"atelier" if hybrid else "long","outfit":styles,"overlays":[]}
        p["colors"].update(skin="#e8bfac",hair="#46364a",eyes="#596a74",outfit=dict(zip(styles,palette)))
        for k in ("shoulders","hips","torso"):
            p["proportions"][k]*=width
        yield dict(name=name,person=p,base="lookdev/anim/own-clips.glb",height=height,proportions=p["proportions"])

if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("look",type=Path)
    ap.add_argument("input_book",type=Path)
    ap.add_argument("output_book",type=Path)
    args=ap.parse_args()
    book=json.loads(args.input_book.read_text())
    book["recipes"].extend(lines(args.look))
    args.output_book.write_text(json.dumps(book,indent=2))
