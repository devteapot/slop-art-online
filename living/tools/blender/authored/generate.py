"""Export the three Blender masters into an existing PNG lookdev tree. No bundling.
BLENDER=$HOME/.local/share/slop-tools/build-bin/blender python3 generate.py LOOKDEV [--bc7 PATH]
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from textile import paint, map_piece
from merge_primitives import read_glb, write_glb

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parents[1]
CHAR = TOOLS/"characters"
EXTRAS = ["jersey_smock-f","smock_bands-f","trousers-f","boots-f"]


def run(*args):
    subprocess.run([str(a) for a in args], check=True)


def export(blender, master, out, *args):
    run(blender,"-b","-t","2","--python-exit-code","1","-P",HERE/"export_master.py","--",HERE/master,out,*args)


def generate(look, encoder):
    blender = os.environ["BLENDER"]
    pages=look/"pages"
    with tempfile.TemporaryDirectory() as tmp:
        temp=Path(tmp)
        types=temp/"types"
        types.mkdir()
        shutil.copytree(pages,temp/"pages")
        for band,maturity in [("adult",.92),("youth",.36)]:
            # Both ages derive from one head master. Texture islands, skin weights
            # and identity pivots stay those of its canonical adult-f-a cage.
            f=types/"adult-f-a.glb"
            face=f.with_suffix(".face.png")
            export(blender,"head.blend",f,maturity)
            run(sys.executable,TOOLS/"merge_primitives.py",f,f)
            run(sys.executable,TOOLS/"face_normals.py",f,f,"--png",face)
            run(sys.executable,CHAR/"hair_fit.py","adult-f-a",f)
            run(sys.executable,CHAR/"face_shadow.py",f,"--png",face)
            run(sys.executable,CHAR/"outline_normals.py",f)
            run(sys.executable,CHAR/"share.py","types","--dir",temp/"pages",f)
            dest=look/"types"/f"atelier-{band}-f-a.glb"
            shutil.copyfile(f,dest)
            shutil.copyfile(face,dest.with_suffix(".face.png"))
        for kind,master,name in [("hair","hair.blend","atelier"),("outfit","outfit.blend","atelier-f")]:
            target=look/"styles"/kind/(name+".glb")
            export(blender,master,target)
            run(sys.executable,TOOLS/"merge_primitives.py",target,target)
            run(sys.executable,CHAR/"shade_mean.py",kind,target)
            if kind=="hair":
                run(sys.executable,CHAR/"share.py","strands","--shared",look/"strands.png",target)
            run(sys.executable,CHAR/"outline_normals.py",target)
        png=pages/"atelier-atlas.png"
        paint().save(png)
        outfit=look/"styles/outfit"
        names=["atelier-f"]
        for name in EXTRAS:
            names.append("atelier-"+name)
            shutil.copyfile(outfit/(name+".glb"),outfit/(names[-1]+".glb"))
        for name in names:
            map_piece(outfit/(name+".glb"),name=="atelier-f")
        if encoder:
            ktx=png.with_suffix(".ktx2")
            job=temp/"jobs.json"
            job.write_text(json.dumps([{"in":str(png),"out":str(ktx),"thumb":str(png.with_suffix(".thumb.png")),
                                        "colour":"srgb","mips":"box","zstd":19}]))
            run(encoder,"encode",job,"--threads","1")
            for name in names:
                target=outfit/(name+".glb")
                j,b=read_glb(target)
                j["images"][0]["uri"]="../../pages/"+ktx.name
                write_glb(target,j,b)

if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("lookdev",type=Path)
    ap.add_argument("--bc7",type=Path)
    args=ap.parse_args()
    generate(args.lookdev.resolve(),args.bc7)
