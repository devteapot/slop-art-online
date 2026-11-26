#!/usr/bin/env python3
# Track B2: the contact sheet. sheet.py SHOOT_DIR FULL_DIR PV_DIR VARIETY.png REPORT.json OUT.jpg
import sys, os, glob, json
from PIL import Image, ImageDraw, ImageFont
shoot, full, pv, variety, report, out = sys.argv[1:7]
rep = json.load(open(report))
def font(sz, bold=False):
    for p in ('/usr/share/fonts/rsms-inter-fonts/Inter-%s.ttf' % ('SemiBold' if bold else 'Regular'), '/usr/share/fonts/rsms-inter-fonts/Inter-Light.ttf', '/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf'):
        if os.path.exists(p): return ImageFont.truetype(p, sz)
    return ImageFont.load_default()
F1, F2, F3 = font(44, True), font(28, True), font(20)
BG = (244, 241, 236); INK = (40, 38, 36)
H = 430
def g(pat):
    r = sorted(glob.glob(pat)); return r[0] if r else None
def tile(path, label, crop=None, h=H, zoom=None):
    if not path or not os.path.exists(path):
        im = Image.new('RGB', (h * 3 // 4, h), (200, 200, 200))
    else:
        im = Image.open(path).convert('RGB')
        if zoom:                                   # native crop round the middle (play-camera shots)
            w0, h0 = im.size; zw, zh = zoom; im = im.crop(((w0 - zw) // 2, (h0 - zh) // 2 - zh // 8, (w0 + zw) // 2, (h0 + zh) // 2 - zh // 8))
        if crop:
            w0, h0 = im.size; im = im.crop((int(crop[0] * w0), int(crop[1] * h0), int(crop[2] * w0), int(crop[3] * h0)))
        im = im.resize((max(1, int(im.width * h / im.height)), h), Image.LANCZOS)
    t = Image.new('RGB', (im.width, h + 30), BG); t.paste(im, (0, 0))
    ImageDraw.Draw(t).text((2, h + 3), label, fill=INK, font=F3); return t
def row(tiles, gap=8):
    w = sum(t.width for t in tiles) + gap * (len(tiles) - 1); r = Image.new('RGB', (w, max(t.height for t in tiles)), BG); x = 0
    for t in tiles: r.paste(t, (x, 0)); x += t.width + gap
    return r
def head(text, f=F2, w=100):
    t = Image.new('RGB', (2600, f.size + 16), BG); ImageDraw.Draw(t).text((0, 6), text, fill=INK, font=f); return t
rows = [head('Bake-off track B2: one base human, shown as four people', F1),
        head('Game renderer (asset view, 11:00) unless a tile says Blender. One quad cage -> two subdivisions -> 8 morphs; height is the armature\'s scale.', F3)]
S = lambda c, pat: g(os.path.join(shoot, 'b2-%s' % c, pat)); FU = lambda c, pat: g(os.path.join(full, 'b2-%s' % c, pat)); P = lambda n: os.path.join(pv, n)
body = (.20, .04, .80, .98)
rows.append(head('Stage 1: the base (the young woman), bind pose, underlayer, no clothing layers'))
rows.append(row([tile(FU('woman', '90-*'), 'bind, front', body), tile(FU('woman', '91-*'), 'bind, three-quarter', body),
                 tile(FU('woman', '92-*'), 'bind, side', body), tile(FU('woman', '93-*'), 'bind, back', body),
                 tile(S('woman', '03-*'), 'face close-up (idle)', (.25, 0, .75, 1)), tile(S('woman', '04-*'), 'hands close-up (idle)', (.12, 0, .88, 1))]))
rows.append(row([tile(P('cage-tq.png'), 'Blender: the cage (1,094 vertices, all quads but the poles)', (.1, .02, .9, .98)),
                 tile(P('wire-up_tq.png'), 'Blender: subdivided twice, shoulder'), tile(P('wire-lo_tq.png'), 'Blender: hips and knees'),
                 tile(P('wire-hand.png'), 'Blender: hand'),
                 tile(FU('woman', '*run*'), 'run (clip)', body), tile(FU('woman', '*sit_ground*'), 'sit_ground (clip)', body),
                 tile(S('woman', '10-*'), 'walk (clip)', (.3, .05, .7, 1))]))
if len(sys.argv) > 8:
    L = lambda pat: g(os.path.join(sys.argv[7], 'b2-woman-l1', pat)); r1 = json.load(open(sys.argv[8]))['woman']
    rows.append(head('The same person at one subdivision: %s triangles (body %s) against %s; same cage, weights, morphs and face layer' % (
        format(r1['total_triangles'], ','), format(r1['triangles']['Body'], ','), format(rep['woman']['total_triangles'], ',')), F3))
    rows.append(row([tile(L('03-*'), 'one subdivision: idle, front', (.28, .0, .72, 1), h=300), tile(L('00-*'), 'one subdivision: face', (.25, 0, .75, 1), h=300),
                     tile(S('woman', '03-*'), 'two subdivisions: face', (.25, 0, .75, 1), h=300),
                     tile(L('01-*'), 'one subdivision: Near 8 m', zoom=(300, 300), h=300), tile(S('woman', '05-*'), 'two: Near 8 m', zoom=(300, 300), h=300),
                     tile(L('02-*'), 'one subdivision: Middle 12 m', zoom=(300, 300), h=300), tile(S('woman', '06-*'), 'two: Middle 12 m', zoom=(300, 300), h=300)]))
rows.append(head('Stage 2: the same base as four people (morph mix + armature scale + colours + hair piece + painted face layer)'))
for c in ('woman', 'man', 'elder', 'child'):
    r = rep[c]; mix = ', '.join('%s %.2g' % kv for kv in r['mix'].items()) or 'the base'
    rows.append(head('%s: %s; scale %.3g; %s triangles, %d materials, %d bones' % (c, mix, r['scale'], format(r['total_triangles'], ','), len(r['materials']), r['bones']), F3))
    rows.append(row([tile(FU(c, '*idle*front*'), 'idle, front', body), tile(FU(c, '*idle*three-quarter*'), 'idle, three-quarter', body),
                     tile(FU(c, '*idle*back*'), 'idle, back', body), tile(S(c, '03-*'), 'face close-up', (.25, 0, .75, 1)),
                     tile(S(c, '04-*'), 'hands close-up', (.12, 0, .88, 1)),
                     tile(S(c, '05-*'), 'Near 8 m (native crop)', zoom=(300, 400)), tile(S(c, '06-*'), 'Middle 12 m (native crop)', zoom=(300, 400)),
                     tile(S(c, '07-*'), 'play camera (native crop)', zoom=(300, 400)), tile(S(c, '11-*'), 'walk', (.3, .05, .7, 1))]))
rows.append(head('Variation: sixteen people from the same file (Blender render; morphs mixed, heights 0.62 to 1.04, colours, four hair pieces, four face layers)'))
v = Image.open(variety).convert('RGB'); rows.append(v.resize((2600, int(v.height * 2600 / v.width)), Image.LANCZOS))
W = max(r.width for r in rows) + 60; Ht = sum(r.height + 10 for r in rows) + 50
sheet = Image.new('RGB', (W, Ht), BG); y = 24
for r in rows: sheet.paste(r, (30, y)); y += r.height + 10
sheet.save(out, quality=88); print(out, sheet.size, os.path.getsize(out))
