"""Paint one shared sRGB garment atlas and map the existing cloth slots to it."""
from pathlib import Path
import sys
from array import array

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from merge_primitives import append_accessor, read_accessor, read_glb, write_glb


def paint():
    im = Image.new("RGB", (1024, 1024), "#f4f1e7")
    d = ImageDraw.Draw(im)
    # Centre panel: alternating loom stripes, paired sprigs and diamond medallions.
    d.rectangle((18,16,496,1007), fill="#789398")
    for x in range(19,496,8):
        d.line((x,16,x,1007), fill="#839da1")
    for y in range(12,1024,96):
        for x in (100,256,412):
            d.polygon([(x,y+4),(x+30,y+44),(x,y+85),(x-30,y+44)],fill="#536e77",outline="#d4c39c",width=3)
            d.line((x,y+16,x,y+72),fill="#e8dbb4",width=3)
            for k in range(3):
                a=y+25+13*k
                d.polygon([(x,a+13),(x-12,a+4),(x-14,a-2),(x-5,a+2)],fill="#c3baa0")
                d.polygon([(x,a+13),(x+12,a+4),(x+14,a-2),(x+5,a+2)],fill="#ead7ad")
    # Lapels: satin piping, piping shadow and two rows of backstitch.
    d.rectangle((516,8,1012,1015),fill="#d6d3b9")
    for y in range(10,1016,48):
        d.line((547,y,756,y+25,977,y), fill="#859594",width=5)
        d.line((547,y+8,756,y+33,977,y+8), fill="#faf0d4",width=3)
    for x in (532,553,979,994):
        d.rectangle((x,0,x+4,1023),fill="#85725d")
        d.line((x+5,0,x+5,1023),fill="#fff4c8",width=2)
        for y in range(3,1024,18):
            d.line((x+8,y,x+8,y+8),fill="#ad9471",width=2)
    # Plain fabric swatch for the Far LOD and all unchanged garment areas.
    d.rectangle((0,0,15,15),fill="white")
    # Composed cloth chooses its dye mode from the texture thumbnail's mean.
    # An ochre/teal mean makes a white swatch rotate toward pink. Preserve
    # the existing neutral 0.48 linear cloth mean and dye the pieces by slot.
    import numpy as np
    a = np.asarray(im.convert("L"), dtype=float)/255
    lin = np.where(a <= .04045, a/12.92, ((a+.055)/1.055)**2.4)
    lin = np.clip(lin * (.48/lin.mean()), 0, 1)
    srgb = np.where(lin <= .0031308, lin*12.92, 1.055*lin**(1/2.4)-.055)
    neutral = Image.fromarray(np.rint(srgb*255).astype("uint8")).convert("RGB")
    ImageDraw.Draw(neutral).rectangle((0,0,15,15),fill="white")
    return neutral


def map_piece(path, authored):
    j,b = read_glb(path)
    j["images"]=[{"uri":"../../pages/atelier-atlas.png"}]
    j["textures"]=[{"source":0}]
    for mat in j["materials"]:
        mat["pbrMetallicRoughness"]["baseColorTexture"]={"index":0}
    for mesh in j["meshes"]:
        for p in mesh["primitives"]:
            attr=p["attributes"]
            count=j["accessors"][attr["POSITION"]]["count"]
            uv=array("f",[.007,.007])*count
            if authored and mesh["name"]=="Cloth":
                # The existing smock owns UV0; Blender joins the new panels' UVMap as UV1.
                panel,_=read_accessor(j,b,attr.pop("TEXCOORD_1"))
                for k in range(0,len(uv),2):
                    if .01 < panel[k] < .99:
                        uv[k:k+2]=panel[k:k+2]
            attr["TEXCOORD_0"]=append_accessor(j,b,uv,5126,"VEC2",False,34962)
    write_glb(path,j,b)


if __name__=="__main__":
    dst=Path(sys.argv[1])
    paint().save(dst/"pages/atelier-atlas.png")
    for name in sys.argv[2:]:
        map_piece(dst/"styles/outfit"/(name+".glb"),name=="atelier-f")
