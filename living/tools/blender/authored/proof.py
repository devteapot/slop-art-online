"""Capture the comparison, pose samples, or paired crowd runs on a private worktree.
Usage: python3 proof.py photos|clips|crowd GAME OUTPUT
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from lineup import lines, TOOLS
sys.path.insert(0,str(TOOLS/"characters"))
from crowd import run_game

GAME=TOOLS.parent/"game"
BOOK=GAME/"assets/characters/recipes.json"
LOOK=GAME/"assets/lookdev"
PORTRAIT=["0:6:0.27:0.92","38:6:0.27:0.92"]
PLAY=["near@0","near@38","middle@0","middle@38"]
CLIPS=["idle","walk","run","talk","sit_idle"]


def room():
    subprocess.run(["df","-h","/"],check=True)
    fs=os.statvfs("/")
    if fs.f_bavail*fs.f_frsize < 55.3*2**30:
        raise RuntimeError("insufficient space for another capture above the 55 GiB reserve")


def capture(mode, binary, out):
    original=BOOK.read_bytes()
    book=json.loads(original)
    recipes=list(lines(LOOK))
    book["recipes"].extend(recipes)
    out.mkdir(parents=True,exist_ok=True)
    try:
        if mode=="crowd":
            results=[]
            for i,who in enumerate(("control","atelier","atelier","control")):
                room()
                book["crowd"]=[who]*64
                BOOK.write_text(json.dumps(book))
                env=dict(LIVING_GAME_COMPOSE="1",LIVING_GAME_CROWD="64:1",LIVING_GAME_LOD_CAP="8",
                         LIVING_GAME_LOD_NEAR_PX="1",LIVING_GAME_LOD_FAR_PX="0.5",LIVING_GAME_PERF="frames,diag,views")
                results.append(run_game(str(out),f"{i}-{who}",env,24,"1600x900",photo=False,binary=str(binary)))
                (out/"results.json").write_text(json.dumps(results,indent=2))
        else:
            room()
            subjects=["shino"]+[r["name"] for r in recipes]
            shots=["idle@1.0/"+v for v in PORTRAIT+PLAY]
            if mode=="clips":
                subjects=["atelier","atelier-broad","atelier-youth"]
                shots=[c+"@"+t+"/30:6:0.93:0.53" for c in CLIPS for t in (".18",".58")]
            BOOK.write_text(json.dumps(book))
            env=dict(os.environ,LIVING_GAME_VIEW=",".join("recipe:"+s for s in subjects),
                     LIVING_GAME_VIEW_OUT=str(out),LIVING_GAME_VIEW_SHOTS=",".join(shots),
                     LIVING_GAME_VIEW_JOINTS=str(out/"joints.jsonl"),LIVING_GAME_VIEW_PLATE=str(int(mode=="photos")),
                     LIVING_GAME_COMPOSE="1",LIVING_GAME_SIZE="1600x900",LIVING_GAME_FAR="1000",
                     LIVING_GAME_HOUR="10",RUST_LOG="warn,living_game=info,living_game::characters::compose=debug")
            with (out/"view.log").open("w") as log:
                subprocess.run([binary],cwd=GAME,env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=800)
    finally:
        BOOK.write_bytes(original)


if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mode",choices=["photos","clips","crowd"])
    ap.add_argument("game",type=Path)
    ap.add_argument("output",type=Path)
    args=ap.parse_args()
    capture(args.mode,args.game.resolve(),args.output.resolve())
