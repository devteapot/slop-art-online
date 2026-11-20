"""Measure display luma and mean row coverage in registered plait windows."""
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

LUMA = np.array([.2126, .7152, .0722])
# Rear silhouette stations on original turnaround. Coordinates include ink.
REAR = [(112,637,674),(118,635,676),(125,635,676),(131,637,673),
        (135,642,670),(141,639,672),(146,638,672),(151,639,671),
        (156,641,669),(161,644,667),(167,641,669),(172,641,669),
        (178,642,668),(185,645,665),(191,644,666),(196,643,667),
        (202,645,665),(209,646,664),(216,645,665),(223,646,663),(229,646,663)]
SHOTS = {'near_180': (432,29), 'middle_180': (439,18)}
def rgb(path):
    return np.asarray(Image.open(path).convert('RGB'),dtype=float)

def describe(image, mask):
    lum=image@LUMA
    n=mask.sum(axis=1)
    return dict(mean_luma=float(lum[mask].mean()),mean_width_px=float(n.mean()),
                proximal_width_px=float(n[:max(1,len(n)//3)].mean()),
                distal_width_px=float(n[-max(1,len(n)//3):].mean()),rows=int(len(n)))

def references(sheet,crown):
    image=rgb(sheet)
    body=image[112:230,626:685]
    ys=np.arange(112,230)
    y,left,right=np.array(REAR).T
    xs=np.arange(626,685)[None,:]
    region=(xs>=np.interp(ys,y,left)[:,None])&(xs<=np.interp(ys,y,right)[:,None])
    rear=describe(body,region)
    # The overhead shows only the exposed lobes above the crown.
    body=image[563:581,1636:1694]
    r,g,b=np.moveaxis(body,-1,0)
    traced=(r>1.36*g)&(g>1.12*b)
    for row in traced:
        inds=np.flatnonzero(row)
        row[inds[0]:inds[-1]+1]=True
    over=describe(body,traced)
    for stats,reference_span in [(rear,108),(over,80)]:
        for key in ('mean_width_px','proximal_width_px','distal_width_px'):
            stats[key]*=crown/reference_span
    return rear,over

def sample(beauty, diagnostic, shot, rows=None):
    top,crown=SHOTS[shot]
    if rows is None:
        rows=round(118*(crown/108)*math.cos(math.radians(58)))
    roi=np.s_[top:top+rows,775:831]
    a,b=rgb(beauty)[roi],rgb(diagnostic)[roi]
    mask=(b[:,:,1]-a[:,:,1]>32)&(b[:,:,1]-b[:,:,0]>28)&(b[:,:,1]-b[:,:,2]>28)
    return describe(a,mask)

def shots(folder):
    return json.loads((folder/'report.json').read_text())['shots']

def measure(sheet, arms):
    results={}
    for shot,(top,crown) in SHOTS.items():
        rear,over=references(sheet,crown)
        results[shot]={'rear drawing':rear,'overhead visible lobes':over}
        for arm,(beauty,diagnostic) in arms.items():
            results[shot][arm]=sample(shots(beauty)[shot],shots(diagnostic)[shot],shot)
    return results

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('turnaround',type=Path)
    parser.add_argument('--arm',action='append',nargs=3,required=True,metavar=('NAME','BEAUTY','PLAIT_ID'))
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    arms={name:(Path(beauty),Path(marked)) for name,beauty,marked in args.arm}
    result=measure(args.turnaround,arms)
    for shot,(top,crown) in SHOTS.items():
        rows=round(18*crown/80*math.sin(math.radians(58)))
        result[shot]['short_overhead_comparison']={
            name:sample(shots(view)[shot],shots(marked)[shot],shot,rows)
            for name,(view,marked) in arms.items()}
    args.out.write_text(json.dumps(result,indent=2)+'\n')
