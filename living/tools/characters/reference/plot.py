"""Sections and profiles of two heads, normalised by head height, as one PNG (PIL)."""
import sys, os, json, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import pil
from PIL import Image, ImageDraw, ImageFont
out = sys.argv[1]; heads = [(a.split('=')[0], json.load(open(a.split('=')[1]))) for a in sys.argv[2:]]
COL = [(205,60,50), (40,90,200), (40,150,80), (150,90,180)]
def norm(d):
    H, chin = d['H'], d['chin']; ey = d['eye'][1]
    # z of the midline front at eye height (face looks +z)
    prof = np.array(d['prof']['0.00']).reshape(-1,3)
    near = prof[np.abs(prof[:,1]-ey) < 0.006]
    z0 = near[:,2].max() if len(near) else prof[:,2].max()
    return H, chin, z0
F = ImageFont.load_default()
def panel(title, w, h):
    im = Image.new('RGB', (w, h), 'white'); d = ImageDraw.Draw(im); d.text((6, 4), title, fill='black', font=F); return im, d
S = 360  # pixels per head-height
# 1. top view: sections at chosen heights, overlay of all heads
levels = [('0.88 crown', '0.88'), ('0.64 forehead', '0.64'), ('0.52 brow', '0.52'), ('0.40 eyes', '0.40'), ('0.28 cheekbone', '0.28'), ('0.20 nose base', '0.20'), ('0.12 mouth/jaw', '0.12'), ('0.04 chin', '0.04')]
# eye level is per head; use each head's eye share for the 'eyes' row
tiles = []
for label, key in levels:
    im, dr = panel('section at ' + label + ' of head height', 300, 260)
    cx, cy = 150, 40
    for hi, (name, d) in enumerate(heads):
        H, chin, z0 = norm(d)
        k = key
        if 'eyes' in label: k = min(d['secs'], key=lambda s: abs(float(s) - (d['eye'][1]-chin)/H))
        else: k = min(d['secs'], key=lambda s: abs(float(s) - float(key)))
        for a, b in d['secs'][k]:
            a, b = np.array(a), np.array(b)
            pa = (cx + a[0]/H*S*0.55, cy + (z0 - a[2])/H*S*0.55); pb = (cx + b[0]/H*S*0.55, cy + (z0 - b[2])/H*S*0.55)
            dr.line([pa, pb], fill=COL[hi], width=2)
    dr.line([(cx, cy-5), (cx, 255)], fill=(200,200,200)); dr.line([(10, cy), (290, cy)], fill=(225,225,225))
    tiles.append(im)
# 2. profiles: midline and off-midline
prof_tiles = []
for pk, label in (('0.00', 'midline profile'), ('0.15', 'profile 0.15 H off the midline (through the eye)'), ('0.30', 'profile 0.30 H off the midline (cheek, temple)')):
    im, dr = panel(label, 300, 520)
    for hi, (name, d) in enumerate(heads):
        H, chin, z0 = norm(d)
        segs = d['prof'].get(pk, [])
        for a, b in segs:
            a, b = np.array(a), np.array(b)
            pa = (190 + (a[2]-z0)/H*S, 500 - (a[1]-chin)/H*S*1.25); pb = (190 + (b[2]-z0)/H*S, 500 - (b[1]-chin)/H*S*1.25)
            dr.line([pa, pb], fill=COL[hi], width=2)
        ey = (d['eye'][1]-chin)/H
        dr.line([(250, 500-ey*S*1.25), (290, 500-ey*S*1.25)], fill=COL[hi], width=3)
    dr.line([(190, 20), (190, 510)], fill=(220,220,220))
    prof_tiles.append(im)
W = 300*4; Ht = 260*2 + 520 + 30
sheet = Image.new('RGB', (W, Ht), 'white'); dr = ImageDraw.Draw(sheet)
for i, t in enumerate(tiles): sheet.paste(t, ((i%4)*300, 30 + (i//4)*260))
for i, t in enumerate(prof_tiles): sheet.paste(t, (i*300, 30 + 520))
x = 6
for hi, (name, d) in enumerate(heads):
    dr.rectangle([x, 8, x+14, 20], fill=COL[hi]); dr.text((x+18, 8), name, fill='black', font=F); x += 18 + 8*len(name) + 20
dr.text((x+10, 8), 'normalised by head height (chin to crown); aligned on the midline and the front of the face at eye height; top views: up the page is forward', fill=(80,80,80), font=F)
im, d2 = panel('legend: ticks at right of profiles = eye centre height', 300, 520)
sheet.paste(im, (900, 550))
sheet.save(out)
