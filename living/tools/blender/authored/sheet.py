"""Lay out Bevy's photographs. Each gameplay pixel occupies exactly one sheet pixel."""
from pathlib import Path
import sys
from PIL import Image,ImageDraw,ImageFont

def font(size,bold=False):
    name="Bold" if bold else "Regular"
    return ImageFont.truetype(f"/usr/share/fonts/rsms-inter-fonts/Inter-{name}.ttf",size)

def shots(folder):
    return sorted(p for p in folder.glob("[0-9][0-9]-*.png") if not p.name.endswith(".plate.png"))

def sheet(photos,clips,out):
    rows=[("shino","Shino","VRoid reference","1.75 m"),("control","Procedural","Adult · seed 71","1.65 m · standard"),
          ("atelier","Hybrid","Adult · seed 71","1.65 m · standard"),("atelier-youth","Hybrid","Youth · seed 163","1.53 m · narrow"),
          ("atelier-broad","Hybrid","Adult · seed 294","1.74 m · broad")]
    widths=[336,336,250,250,250,250]
    margin=30;left=235;gap=10
    width=left+sum(widths)+gap*5+margin
    row_h=322; top=153; bottom=top+5*row_h
    im=Image.new("RGB",(width,bottom+382),"#151b23")
    d=ImageDraw.Draw(im)
    def text(x,y,words,size=20,colour="#e7eaee",bold=False):
        d.text((x,y),words,font=font(size,bold),fill=colour)
    text(margin,18,"Character study   /   Authored Blender bases",36,bold=True)
    text(margin,70,"Bevy asset view  ·  1600 × 900  ·  idle held at 1.0 s  ·  58° play camera  ·  portrait crops reduced  ·  gameplay crops at native pixel size",21,"#b6c6cd")
    headers=["Portrait  /  front","Portrait  /  38°","Near 8 m  /  front","Near 8 m  /  38°","Middle 12 m  /  front","Middle 12 m  /  38°"]
    x=left
    for w,title in zip(widths,headers):
        text(x,117,title,20,bold=True);x+=w+gap
    for i,(slug,title,meta,sub) in enumerate(rows):
        y=top+i*row_h
        d.line((margin,y-5,width-margin,y-5),fill="#44505b")
        text(margin,y+96,title,29,bold=True)
        text(margin,y+143,meta,19,"#c9d5d9")
        text(margin,y+174,sub,18,"#a8babe")
        x=left
        imgs=shots(photos/("recipe:"+slug))
        if len(imgs)!=6: raise ValueError((slug,len(imgs)))
        for j,(w,f) in enumerate(zip(widths,imgs)):
            scene=Image.open(f).convert("RGB")
            if j<2:
                tile=scene.crop((495,265,1105,829)).resize((w,310),Image.Resampling.LANCZOS)
                im.paste(tile,(x,y))
            else:
                im.paste(scene.crop((675,328,925,578)),(x,y+31))
            x+=w+gap
    text(margin,bottom+5,"Hybrid   /   J_Bip clip samples",25,bold=True)
    text(margin,bottom+42,"Adult, seed 71  ·  single frames from the same Bevy session  ·  each source clip was sampled at 0.18 and 0.58 s on all three variants",19,"#b6c6cd")
    files=shots(clips/"recipe:atelier")
    for j,(name,k) in enumerate([("Idle",1),("Walk",2),("Run",5),("Talk",7),("Sit idle",9)]):
        cell=(width-2*margin)//5
        src=Image.open(files[k]).convert("RGB")
        tile=src.crop((395,80,1205,890)).resize((245,245),Image.Resampling.LANCZOS)
        x=margin+j*cell+(cell-245)//2
        im.paste(tile,(x,bottom+85))
        text(x,bottom+338,name,20,bold=True)
    im.save(out,optimize=True)

if __name__=="__main__":
    sheet(*(Path(s) for s in sys.argv[1:]))
