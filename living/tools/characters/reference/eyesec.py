"""Vertical section through an eye's centre, every face primitive in its own colour (glTF, faces -Z)."""
import sys, os, json, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import pil
from PIL import Image, ImageDraw
from geo import load, section
path, out, x0 = sys.argv[1], sys.argv[2], float(sys.argv[3])
tris, bones, g = load(path, lambda m: ('_FACE' in m or '_EYE' in m or '_SKIN' in m) and 'Body' not in m)
COL = {'Face_00_SKIN':(150,150,150), 'EyeWhite':(90,160,220), 'Eye_00':(90,160,220), 'EyeIris':(40,90,200), 'EyeHighlight':(240,180,40), 'FaceEyeline':(200,40,40), 'FaceEyelash':(230,90,150), 'FaceBrow':(120,70,30), 'FaceMouth':(160,60,120), 'EyeExtra':(60,200,120)}
im = Image.new('RGB', (560, 560), 'white'); d = ImageDraw.Draw(im)
allp = np.concatenate([t[0] for t in tris]); 
ey = bones.get('J_Adj_L_FaceEye', allp.mean(0))[1]
zf = None
S = 5600  # px per metre
legend = {}
secs = [(mat, section(P, I, 0, x0)) for P, N, I, mat, uv in tris if 'Hair' not in mat]
zc = np.concatenate([q.reshape(-1,3) for m_, q in secs if len(q) and ('EYE' in m_)])[:,2].mean()
for P, N, I, mat, uv in tris:
    if 'Hair' in mat: continue
    s = section(P, I, 0, x0)
    if len(s) == 0: continue
    key = next((k for k in COL if k in mat), None)
    c = COL.get(key, (0,0,0)); legend[key] = c
    for a, b in s:
        pa = (280 + (zc - a[2]) * S, 280 - (a[1]-ey)*S); pb = (280 + (zc - b[2])*S, 280 - (b[1]-ey)*S)
        d.line([pa, pb], fill=c, width=2)
y = 6
for k, c in legend.items(): d.rectangle([6, y, 18, y+10], fill=c); d.text((22, y-1), k, fill='black'); y += 14
d.text((6, 540), f'section at x={x0*100:.1f} cm; forward is right; 1 cm = {S/100:.0f} px', fill='black')
# 1 cm scale bar
d.line([(440, 540), (440+S/100, 540)], fill='black', width=3)
# centre the drawing on the content: crop later
im.save(out)
