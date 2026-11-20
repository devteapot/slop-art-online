"""Place one broad curved highlight on the upper arc of each exposed braid lobe."""
import json
from pathlib import Path
import sys
import numpy as np
from PIL import Image

def paint(layout_path, mask_path):
    layout=json.loads(layout_path.read_text())
    rgb=np.array(Image.open(mask_path).convert('RGB'))
    braid=[s for s in layout['islands'] if s['kind']=='braid']
    for strand,spec in enumerate(braid):
        l,t,r,b=spec['box']
        along=(np.arange(t,b+1)[:,None]-t)/(b-t)
        angle=(np.arange(l,r+1)[None,:]-l)/(r-l)*2*np.pi
        phase=2*np.pi*(2.90*along+strand/3+.04)
        outward=-np.cos(angle)
        segment_top=-np.sin(2*phase+.32*np.sin(angle))
        coverage=np.clip((segment_top-.14)/.28,0,1)*np.clip((outward-.05)/.30,0,1)
        rgb[t:b+1,l:r+1,0]=np.rint(255*coverage)
    Image.fromarray(rgb).save(mask_path)

if __name__=='__main__':
    paint(*map(Path,sys.argv[1:]))
