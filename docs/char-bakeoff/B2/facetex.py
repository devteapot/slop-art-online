#!/usr/bin/env python3
# Track B2: the painted face layer (eyes, lashes, brows, nose mark, mouth, blush), one 1024x1024 RGBA picture a person.
# Coordinates are the head's own (metres at head scale 1): x across, z up from the head joint; the window is
# x -0.09..0.09, z -0.05..0.13, the same planar map base.py gives the face layer.
# Usage: facetex.py OUT_DIR [name...]
import sys, os, math, random
try:
    from PIL import Image, ImageDraw, ImageFilter
except ImportError:      # Blender's Python: base.py only reads SPECS
    Image = None

S = 2048
def px(x, z): return ((x + 0.09) / 0.18 * S, (1 - (z + 0.05) / 0.18) * S)
def m2p(m): return m / 0.18 * S

def cr(pts, n=14):
    """Catmull-Rom through pts"""
    out = []
    P = [pts[0]] + list(pts) + [pts[-1]]
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        for s in range(n):
            t = s / n
            out.append(tuple(0.5 * ((2 * p1[k]) + (-p0[k] + p2[k]) * t + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * t * t
                                    + (-p0[k] + 3 * p1[k] - 3 * p2[k] + p3[k]) * t ** 3) for k in (0, 1)))
    out.append(tuple(pts[-1]))
    return out

def stroke(d, pts, wfn, col):
    """a tapered stroke along pts (metres); wfn(t) is the half width"""
    L, R = [], []
    n = len(pts)
    for i, p in enumerate(pts):
        a = pts[max(0, i - 1)]; b = pts[min(n - 1, i + 1)]
        tx, tz = b[0] - a[0], b[1] - a[1]; l = math.hypot(tx, tz) or 1
        nx, nz = -tz / l, tx / l; w = wfn(i / (n - 1))
        L.append(px(p[0] + nx * w, p[1] + nz * w)); R.append(px(p[0] - nx * w, p[1] - nz * w))
    d.polygon(L + R[::-1], fill=col)

def ell(d, x, z, rx, rz, col):
    a = px(x - rx, z + rz); b = px(x + rx, z - rz); d.ellipse([a[0], a[1], b[0], b[1]], fill=col)

def hexa(h, a=255):
    h = h.lstrip('#'); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) + (a,)
def mixc(a, b, t): return tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3)) + (255,)

SPECS = {
    'woman': dict(hw=.0178, hh=.0152, ex=.0335, ez=.0595, tilt=.0020, iris='#5f8f5a', lash='#3a1f18', brow='#7a3420',
                  brow_w=.0030, brow_z=.0235, lashw=.0034, blush=.30, mouth='#a24a44', mouth_w=.0125, freckles=True, smile=.0016),
    'man': dict(hw=.0160, hh=.0090, ex=.0335, ez=.061, tilt=.0006, iris='#6b5a3c', lash='#241a16', brow='#241d1a',
                brow_w=.0046, brow_z=.0205, lashw=.0026, blush=.06, mouth='#8a4a40', mouth_w=.0150, smile=.0004, lower_lash=False, nose_len=.012),
    'elder': dict(hw=.0150, hh=.0088, ex=.0335, ez=.061, tilt=-.0008, iris='#6d8794', lash='#4a403c', brow='#b9b9b6',
                  brow_w=.0044, brow_z=.0215, lashw=.0022, blush=.10, mouth='#8a5048', mouth_w=.0140, smile=.0002, lower_lash=False,
                  wrinkles=True, moustache='#cfcfcc', nose_len=.014),
    'child': dict(hw=.0188, hh=.0170, ex=.0345, ez=.057, tilt=.0010, iris='#7a5a2e', lash='#3a2416', brow='#8a5a22',
                  brow_w=.0022, brow_z=.0300, lashw=.0028, blush=.38, mouth='#b0504a', mouth_w=.0095, smile=.0022, freckles=False),
}
SKIN_SHADOW = '#c98672'

def eye(img, sp, sg):
    hw, hh, ex, ez = sp['hw'], sp['hh'], sp['ex'], sp['ez']
    X = lambda x: sg * x
    inner = (ex - hw, ez - .10 * hh - sp['tilt']); outer = (ex + hw, ez + .12 * hh + sp['tilt'])
    upper = cr([inner, (ex - .55 * hw, ez + .72 * hh), (ex + .02 * hw, ez + hh), (ex + .60 * hw, ez + .80 * hh), outer])
    lower = cr([outer, (ex + .62 * hw, ez - .70 * hh), (ex + .02 * hw, ez - .96 * hh), (ex - .60 * hw, ez - .66 * hh), inner])
    poly = [px(X(x), z) for x, z in upper + lower]
    mask = Image.new('L', (S, S), 0); ImageDraw.Draw(mask).polygon(poly, fill=255)
    lay = Image.new('RGBA', (S, S), (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    d.rectangle([0, 0, S, S], fill=(250, 247, 243, 255))
    # the lid's shadow on the white
    d.polygon([px(X(x), z - (0 if i == 0 else 0)) for i, (x, z) in enumerate(upper)] +
              [px(X(x), z - .42 * hh) for x, z in upper[::-1]], fill=(214, 204, 210, 255))
    ic = hexa(sp['iris']); dark = mixc(ic, (20, 18, 24), .62); light = mixc(ic, (255, 250, 220), .42)
    ix, iz = ex - .03 * hw, ez - .02 * hh; rx, rz = .58 * hw, min(1.04 * hh, .62 * hw * 1.25)
    ell(d, X(ix), iz, rx, rz, dark)
    ell(d, X(ix), iz - .04 * rz, rx * .86, rz * .88, ic)
    ell(d, X(ix), iz - .38 * rz, rx * .62, rz * .46, light)
    ell(d, X(ix), iz + .02 * rz, rx * .40, rz * .46, (22, 16, 20, 255))
    sh = Image.new('RGBA', (S, S), (0, 0, 0, 0)); ds = ImageDraw.Draw(sh)
    a = px(X(ix) - rx * 1.1, iz + rz * 1.1); b = px(X(ix) + rx * 1.1, iz + rz * .30)
    ds.rectangle([min(a[0], b[0]), a[1], max(a[0], b[0]), b[1]], fill=dark[:3] + (120,))
    lay = Image.alpha_composite(lay, sh); d = ImageDraw.Draw(lay)
    ell(d, ix * sg - rx * .34, iz + rz * .46, rx * .30, rz * .24, (255, 255, 255, 255))     # highlights: the same side on both eyes
    ell(d, ix * sg + rx * .36, iz - .40 * rz, rx * .14, rz * .12, (255, 255, 255, 230))
    out = Image.new('RGBA', (S, S), (0, 0, 0, 0)); out.paste(lay, (0, 0), mask)
    img.alpha_composite(out)
    d = ImageDraw.Draw(img)
    lc = hexa(sp['lash'])
    # the upper lash line, heavier toward the outer corner, with a short wing
    wing = (ex + hw + .0042, ez + .12 * hh + sp['tilt'] + .0030)
    up2 = [(x, z + .0006) for x, z in upper] + [wing]
    stroke(d, [(X(x), z) for x, z in up2], lambda t: sp['lashw'] * (0.30 + 0.70 * math.sin(math.pi * min(1, t * 1.02)) ** 0.7) * (0.75 + 0.5 * t) * .5 + .0003, lc)
    if sp.get('lower_lash', True):
        lo = lower[:len(lower) // 2]
        stroke(d, [(X(x), z - .0003) for x, z in lo], lambda t: .00055 * (1 - t) + .0002, lc[:3] + (210,))
    else:
        lo = lower[:len(lower) // 3]
        stroke(d, [(X(x), z - .0003) for x, z in lo], lambda t: .0004 * (1 - t) + .0001, lc[:3] + (160,))
    # the lid's fold
    fold = [(x, z + .0034 + .0010 * math.sin(math.pi * i / (len(upper) - 1))) for i, (x, z) in enumerate(upper)][3:-2]
    stroke(d, [(X(x), z) for x, z in fold], lambda t: .00045 * math.sin(math.pi * t) + .0001, hexa(SKIN_SHADOW, 200))
    # the brow
    bz = ez + hh + sp['brow_z'] - .0138
    bc = hexa(sp['brow'])
    br = cr([(ex - hw * 1.02, bz - .0012 - sp['tilt']), (ex - .2 * hw, bz + .0032), (ex + .55 * hw, bz + .0030), (ex + hw * 1.22, bz - .0006 + sp['tilt'])])
    stroke(d, [(X(x), z) for x, z in br], lambda t: sp['brow_w'] * (1.0 - 0.72 * t ** 1.4) * .5 + .0002, bc)
    if sp.get('wrinkles'):
        for k in range(3):
            a0 = (ex + hw + .004, ez - .001 + k * .0030); a1 = (ex + hw + .0115, ez - .004 + k * .0055)
            stroke(d, [(X(a0[0]), a0[1]), (X(a1[0]), a1[1])], lambda t: .00035 * (1 - t) + .0001, hexa(SKIN_SHADOW, 190))
        bag = cr([(ex - .7 * hw, ez - hh - .0030), (ex, ez - hh - .0052), (ex + .75 * hw, ez - hh - .0030)])
        stroke(d, [(X(x), z) for x, z in bag], lambda t: .0004 * math.sin(math.pi * t) + .0001, hexa(SKIN_SHADOW, 170))

def paint(name, path):
    sp = SPECS[name]
    img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    # blush, soft
    bl = Image.new('RGBA', (S, S), (0, 0, 0, 0)); d = ImageDraw.Draw(bl)
    for sg in (-1, 1): ell(d, sg * .041, .030, .019, .0095, (238, 118, 108, int(255 * sp['blush'])))
    bl = bl.filter(ImageFilter.GaussianBlur(m2p(.0055)))
    img.alpha_composite(bl)
    d = ImageDraw.Draw(img)
    if sp.get('freckles'):
        random.seed(7)
        for i in range(46):
            x = random.uniform(-.052, .052); z = .034 + random.uniform(-.010, .010) - abs(x) * .10
            if abs(x) < .007 and z < .034: continue
            r = random.uniform(.00045, .00085); ell(d, x, z, r, r, (176, 104, 72, random.randint(90, 160)))
    for sg in (-1, 1): eye(img, sp, sg)
    d = ImageDraw.Draw(img)
    sh = hexa(SKIN_SHADOW, 205)
    # the nose: a small shaded wedge on one side and the tip's underline
    nl = sp.get('nose_len', 0.0)
    d.polygon([px(.0012, .0455 + nl), px(.0058 + nl * .12, .0325), px(.0010, .0315)], fill=hexa(SKIN_SHADOW, 120 + int(nl * 2500)))
    stroke(d, cr([(-.0040, .0300), (0, .0288), (.0042, .0300)]), lambda t: .00050 * math.sin(math.pi * t) + .00012, sh)
    # the mouth
    mw = sp['mouth_w']; mz = .0068; mc = hexa(sp['mouth'])
    line = cr([(-mw, mz + sp['smile']), (-mw * .45, mz - .0004), (0, mz + .0002), (mw * .45, mz - .0004), (mw, mz + sp['smile'])])
    lip = Image.new('RGBA', (S, S), (0, 0, 0, 0)); dl = ImageDraw.Draw(lip)
    ell(dl, 0, mz - .0040, mw * .50, .0022, mc[:3] + (70,)); ell(dl, 0, mz + .0018, mw * .55, .0014, mc[:3] + (55,))
    img.alpha_composite(lip.filter(ImageFilter.GaussianBlur(m2p(.0009))))
    d = ImageDraw.Draw(img)
    stroke(d, line, lambda t: .00078 * math.sin(math.pi * t) ** .6 + .00022, mixc(mc, (60, 20, 20), .35))
    stroke(d, cr([(-mw * .30, mz - .0068), (0, mz - .0075), (mw * .30, mz - .0068)]), lambda t: .0004 * math.sin(math.pi * t) + .0001, hexa(SKIN_SHADOW, 150))
    if sp.get('wrinkles'):
        for sg in (-1, 1):
            nl = cr([(sg * .0105, .0330), (sg * .0170, .0200), (sg * .0195, .0060)])
            stroke(d, nl, lambda t: .00045 * math.sin(math.pi * t) + .00012, hexa(SKIN_SHADOW, 190))
        for z, w in ((.1040, .030), (.1125, .024)):
            stroke(d, cr([(-w, z - .001), (0, z + .0008), (w, z - .001)]), lambda t: .0004 * math.sin(math.pi * t) + .0001, hexa(SKIN_SHADOW, 150))
    if sp.get('moustache'):
        mcol = hexa(sp['moustache'])
        for sg in (-1, 1):
            ms = cr([(sg * .0008, .0230), (sg * .0090, .0190), (sg * .0180, .0120), (sg * .0230, .0050)])
            stroke(d, ms, lambda t: .0042 * (1 - t) ** .8 + .0003, mcol)
            ms2 = cr([(sg * .0020, .0200), (sg * .0100, .0160), (sg * .0170, .0100)])
            stroke(d, ms2, lambda t: .0006 * math.sin(math.pi * t) + .0001, mixc(mcol, (90, 90, 96), .5))
    # the lower strip (under the chin, unused by the open face): the shut eyes and the open mouth, each drawn
    # round ZS where base.py's hidden patches look for them
    ZS = -0.0385
    lc = hexa(sp['lash']); hw, ex = sp['hw'], sp['ex']
    for sg in (-1, 1):
        arc = cr([(sg * (ex - hw), ZS + .0018), (sg * (ex - .35 * hw), ZS - .0022), (sg * (ex + .30 * hw), ZS - .0026), (sg * (ex + hw + .0015), ZS + .0030)])
        stroke(d, arc, lambda t: sp['lashw'] * .5 * (0.45 + 0.55 * math.sin(math.pi * t) ** .7) * (0.8 + 0.4 * t) + .0003, lc)
        for k, (ox, ln) in enumerate(((.55, .0036), (.80, .0040), (1.0, .0036))):
            x0 = ex + hw * ox; z0 = ZS - .0022 + .0034 * max(0, ox - .45) ** 1.5 * 3
            stroke(d, [(sg * x0, z0), (sg * (x0 + ln * .55), z0 - ln * .8)], lambda t: .0006 * (1 - t) + .00012, lc)
        fold = cr([(sg * (ex - .7 * hw), ZS + .0062), (sg * ex, ZS + .0040), (sg * (ex + .8 * hw), ZS + .0070)])
        stroke(d, fold, lambda t: .00045 * math.sin(math.pi * t) + .0001, hexa(SKIN_SHADOW, 190))
    mw = sp['mouth_w'] * .56
    ell(d, 0, ZS, mw + .0008, .0056, mixc(mc, (60, 20, 20), .45)); ell(d, 0, ZS, mw, .0048, (92, 34, 36, 255))
    ell(d, 0, ZS - .0030, mw * .62, .0020, (214, 120, 118, 255))
    img = img.resize((1024, 1024), Image.LANCZOS)
    img.save(path)

if __name__ == '__main__':
    out = sys.argv[1]; os.makedirs(out, exist_ok=True)
    for n in (sys.argv[2:] or list(SPECS)):
        paint(n, os.path.join(out, 'face-%s.png' % n)); print('face', n)
