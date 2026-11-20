"""Draw intermittent rear fold lines in the existing UV islands."""
import json
import math
import sys
from pathlib import Path
from PIL import Image, ImageDraw

def draw(parent, out):
    layout=json.loads((parent/'lock-layout.json').read_text())
    image=Image.open(parent/'lock-lines.png').convert('L')
    mask=Image.open(out/'own-cora-live.hair.png').convert('RGB')
    brush=ImageDraw.Draw(image)
    for island in layout['islands']:
        kind,seed=island['kind'],island['seed']
        if kind not in ('combed','braid') or (kind=='combed' and abs(seed)==1):
            continue
        l,t,r,b=island['box']
        brush.rectangle((l-1,t-1,r+1,b+1),fill=255)
        def stroke(start,end,x0,bend,x1,width=1):
            pts=[]
            for row in range(101):
                u=row/100; x=(1-u)**2*x0+2*(1-u)*u*bend+u*u*x1
                pts.append((round(l+x*(r-l)), round(t+(start+(end-start)*u)*(b-t))))
            brush.line(pts,fill=0,width=width)
        if kind=='combed':
            g=abs(seed);s=1 if seed>0 else -1
            start,end={2:(.44,.91),3:(.27,.91),4:(.12,.96),5:(.42,.73),6:(.15,.90)}[g]
            # A small secondary crease merges into the partner. Long contours
            # have a thicker middle and a single-texel termination at each end.
            stroke(start,end,.50+s*.22,.50+s*.25,.50+s*.10)
            if g in (3,4):
                stroke(start+.14,end-.09,.50+s*.219,.50+s*.22,.50+s*.137,2)
            # The secondary fold gets no independent highlight. Large rear
            # leaves share one upper highlight, stopping before the plait.
            if g in (2,3,5):
                tile=mask.crop((l,t,r+1,b+1));red,green,blue=tile.split()
                mask.paste(Image.merge('RGB',(red.point(lambda x:0),green,blue)),(l,t))
        else:
            # The braid's overlapping lobes supply most of their separation.
            # Short underfold creases reinforce the turns without a grid.
            strand=(seed-1921)//570
            for cross in range(7):
                y=(.19+cross*.5-strand/3)/2.8
                if .03<y<.94:stroke(y,y+.052,.34,.49,.65)
    image.save(out/'lock-lines.png')
    mask.save(out/'own-cora-live.hair.png')
if __name__=='__main__':draw(*map(Path,sys.argv[1:]))
