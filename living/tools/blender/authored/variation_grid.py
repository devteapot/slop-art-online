"""Cross two age masters, three builds and three identities, holding pose and dyes.
Usage: python3 variation_grid.py GAME OUTPUT
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

from lineup import face_types, lines
from proof import BOOK,GAME,LOOK,room


def grid():
    presets=list(lines(LOOK))
    for band,face_source in (("youth",presets[2]),("adult",presets[1])):
        t=face_types.load()["types"][band+"-f-a"]
        for build,preset in zip(("standard","narrow","broad"),presets[1:]):
            for seed in (71,163,294):
                r=deepcopy(face_source)
                p=r["person"]
                r["name"]=f"atelier-{band}-{build}-{seed}"
                r["proportions"]=p["proportions"]=preset["proportions"]
                r["height"]=p["height"]=preset["height"]
                p["identity"]=face_types.draw_valid(t,seed)
                yield r

if __name__=="__main__":
    binary=Path(sys.argv[1]).resolve()
    out=Path(sys.argv[2]).resolve()
    out.mkdir(parents=True,exist_ok=True)
    room()
    original=BOOK.read_bytes()
    try:
        b=json.loads(original)
        rows=list(grid())
        b["recipes"].extend(rows)
        BOOK.write_text(json.dumps(b))
        env=dict(os.environ,LIVING_GAME_VIEW=",".join("recipe:"+r["name"] for r in rows),LIVING_GAME_VIEW_OUT=str(out),
                 LIVING_GAME_VIEW_SHOTS="idle@1.0/38:6:0.45:0.85",LIVING_GAME_VIEW_JOINTS=str(out/"joints.jsonl"),
                 LIVING_GAME_SIZE="720x540",LIVING_GAME_COMPOSE="1",LIVING_GAME_FAR="1000",LIVING_GAME_HOUR="10",
                 RUST_LOG="warn,living_game=info")
        with (out/"view.log").open("w") as log:
            subprocess.run([binary],cwd=GAME,env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=500)
    finally:
        BOOK.write_bytes(original)
