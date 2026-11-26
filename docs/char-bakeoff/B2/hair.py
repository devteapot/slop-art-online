# Track B2: hair as a separate piece: a scalp cap and broad tapered locks laid over the skull's ellipsoid.
# Each lock is a closed solid that ends in a point; its shade (root, band of light, tip, underside) is in the
# vertex colours and its colour is the material's, so a generator can recolour and restyle it.
import bpy, math
import numpy as np

EC = np.array([0.0, 0.0025, 0.090]); ER = np.array([.0860, .1050, .1190])

def sph(az, el, lift=0.0):
    a, e = math.radians(az), math.radians(el)
    d = np.array([math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)])
    return EC + ER * (1 + lift) * d

def catmull(P, n):
    P = [P[0]] + list(P) + [P[-1]]; out = []
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        for s in range(n):
            t = s / n
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    out.append(P[-1]); return out

def sm(a, b, x):
    t = min(1.0, max(0.0, (x - a) / (b - a))); return t * t * (3 - 2 * t)

class Mesh:
    def __init__(self): self.v = []; self.f = []; self.s = []
    def lock(self, ctrl, width, thick=0.30, band=0.34, tone=1.0):
        pts = catmull([sph(*c) for c in ctrl], 4)
        n = len(pts); base = len(self.v); rings = n - 1
        for i in range(rings):
            t = i / (n - 1)
            p = pts[i]; tg = pts[min(n - 1, i + 1)] - pts[max(0, i - 1)]; tg /= np.linalg.norm(tg) + 1e-9
            nr = (p - EC) / ER ** 2; nr -= nr.dot(tg) * tg; nr /= np.linalg.norm(nr) + 1e-9
            b = np.cross(tg, nr)
            w = width * 0.5 * (0.40 + 0.60 * sm(0, .2, t)) * (1 - sm(.45, 1.0, t)) ** 0.85 + .0012
            th = min(.012, thick * w * 2) + .0015
            li = 0.74 + 0.26 * math.exp(-((t - band) / 0.15) ** 2) - 0.10 * sm(.7, 1, t) - 0.12 * (1 - sm(0, .12, t))
            for (cb, cn, sh) in ((1, .15, .93), (.5, 1, 1), (-.5, 1, 1), (-1, .15, .93), (-.5, -.45, .62), (.5, -.45, .62)):
                self.v.append(p + b * cb * w + nr * (cn * th + th * .5)); self.s.append(min(1.0, li * sh * tone))
        self.v.append(pts[-1]); self.s.append(0.78 * tone); tip = len(self.v) - 1
        for i in range(rings - 1):
            for q in range(6):
                a = base + i * 6 + q; b2 = base + i * 6 + (q + 1) % 6
                self.f.append([a, b2, b2 + 6, a + 6])
        last = base + (rings - 1) * 6
        for q in range(6): self.f.append([last + q, last + (q + 1) % 6, tip])
        self.f.append([base + q for q in range(6)][::-1])
    def cap(self, hairline, tone=0.62, lift=0.026, naz=28, nel=8):
        base = len(self.v)
        for i in range(naz):
            az = -180 + 360 * i / naz; e0 = hairline(az)
            for j in range(nel):
                el = e0 + (88 - e0) * j / (nel - 1)
                self.v.append(sph(az, el, lift)); self.s.append(tone * (0.9 + 0.1 * j / (nel - 1)))
        self.v.append(sph(0, 90, lift)); self.s.append(tone); top = len(self.v) - 1
        for i in range(naz):
            i2 = (i + 1) % naz
            for j in range(nel - 1):
                self.f.append([base + i * nel + j, base + i2 * nel + j, base + i2 * nel + j + 1, base + i * nel + j + 1])
            self.f.append([base + i * nel + nel - 1, base + i2 * nel + nel - 1, top])

def hairline(front=38, side=-4, back=-42):
    def f(az):
        a = abs(((az + 180) % 360) - 180)
        return front + (side - front) * sm(0, 1, a / 90) if a < 90 else side + (back - side) * sm(0, 1, (a - 90) / 90)
    return f

def style_woman(m):
    m.cap(hairline(40, -6, -44))
    for az in (100, 126, 152, 178, 204, 230, 256):          # the back and sides, to the jaw, tips turned out
        m.lock([(az, 84, .03), (az, 50, .05), (az, 10, .06), (az + 2, -26, .08), (az + 5, -50, .14), (az + 9, -60, .24)], .066)
    for az in (113, 139, 165, 191, 217, 243):               # a shorter upper layer
        m.lock([(az, 86, .06), (az, 55, .085), (az - 3, 20, .10), (az - 6, -12, .13), (az - 8, -24, .19)], .060, tone=1.0)
    # the side part is on her right (az -28); the fringe sweeps to her left and ends above the brows
    m.lock([(-26, 80, .03), (-8, 62, .075), (16, 42, .095), (40, 24, .09), (56, 8, .09), (60, -8, .14)], .052)
    m.lock([(-28, 79, .03), (-14, 60, .08), (2, 40, .10), (16, 24, .105), (22, 11, .13)], .046)
    m.lock([(-30, 78, .03), (-22, 58, .075), (-14, 38, .095), (-8, 22, .10), (-4, 10, .125)], .042)
    m.lock([(-33, 76, .03), (-30, 56, .07), (-30, 38, .09), (-36, 22, .10), (-42, 10, .13)], .040)
    m.lock([(-24, 82, .04), (6, 66, .10), (34, 46, .115), (52, 30, .12), (60, 18, .16)], .044)
    m.lock([(-12, 84, .03), (50, 64, .06), (78, 32, .07), (84, 0, .07), (80, -30, .10), (74, -52, .17), (68, -62, .27)], .058)
    m.lock([(-40, 78, .03), (-58, 52, .06), (-72, 26, .07), (-80, 0, .07), (-78, -30, .10), (-72, -52, .17), (-66, -62, .27)], .056)
    for sg in (-1, 1):                                        # strands that frame the face
        m.lock([(sg * 62, 46, .07), (sg * 68, 18, .08), (sg * 64, -12, .09), (sg * 59, -36, .12), (sg * 63, -54, .20)], .028)
        m.lock([(sg * 92, 70, .05), (sg * 96, 30, .07), (sg * 94, -10, .08), (sg * 92, -40, .11), (sg * 96, -56, .20)], .058)
    m.lock([(20, 86, .05), (60, 66, .085), (86, 40, .10), (96, 14, .12), (98, -6, .17)], .056)
    m.lock([(-60, 84, .05), (-80, 60, .085), (-92, 36, .10), (-98, 12, .12), (-100, -6, .17)], .054)

def style_man(m):
    m.cap(hairline(44, 6, -26), lift=0.020)
    for az in range(96, 266, 21):                            # short at the back and sides, close to the skull
        m.lock([(az, 78, .03), (az, 52, .04), (az + 3, 26, .04), (az + 5, 2, .04), (az + 6, -14, .06)], .050, thick=.2)
    for az in (-88, -66, 66, 88):
        m.lock([(az * .8, 80, .03), (az, 58, .045), (az * 1.04, 36, .045), (az * 1.06, 20, .065)], .046, thick=.2)
    # the fringe: short, brushed to his left, over the top of the forehead
    for a0, a1, e1, l in ((-40, -46, 34, .09), (-26, -18, 33, .11), (-12, 6, 32, .12), (2, 28, 31, .12), (16, 48, 30, .10)):
        m.lock([(a0, 80, .035), ((a0 + a1) / 2, 64, .075), (a1 * .9, e1 + 14, .09), (a1, e1, l)], .050, thick=.24)
    for az in (115, 155, 195, 235):
        m.lock([(az, 84, .05), (az - 4, 62, .07), (az - 8, 42, .075), (az - 10, 30, .10)], .052, thick=.22)
    m.lock([(0, 88, .045), (-30, 72, .08), (-54, 56, .09), (-64, 46, .12)], .048, thick=.24)
    m.lock([(10, 88, .045), (40, 72, .08), (62, 56, .09), (72, 46, .12)], .048, thick=.24)

def style_elder(m):
    m.cap(hairline(60, 14, -22), lift=0.014, tone=.86)
    for az in range(88, 276, 19):                            # a short fringe round the back and sides
        m.lock([(az, 58, .02), (az + 2, 36, .03), (az + 3, 14, .03), (az + 4, -4, .03), (az + 5, -14, .05)], .046, thick=.2)
    for sg in (-1, 1):
        m.lock([(sg * 66, 58, .02), (sg * 76, 42, .03), (sg * 82, 28, .03), (sg * 84, 18, .05)], .036, thick=.2)
    for az in (120, 160, 200, 240):
        m.lock([(az, 82, .02), (az, 66, .03), (az - 4, 50, .035), (az - 6, 42, .055)], .046, thick=.2)

def style_child(m):
    m.cap(hairline(36, -8, -40))
    for az in range(-50, 51, 20):                            # a straight fringe to just above the brows
        m.lock([(az * .25, 85, .03), (az * .7, 62, .065), (az, 40, .08), (az * 1.03, 22, .08), (az * 1.04, 10, .11)], .050)
    for az in range(70, 291, 20):
        m.lock([(az, 85, .03), (az, 52, .06), (az, 14, .075), (az + 1, -18, .09), (az + 2, -38, .12), (az + 3, -46, .18)], .060)
    for az in (80, 120, 160, 200, 240, 280):
        m.lock([(az, 87, .06), (az + 6, 60, .095), (az + 10, 30, .11), (az + 12, 12, .16)], .056)
    m.lock([(0, 89, .07), (8, 80, .12), (12, 76, .19)], .030)     # a tuft at the crown

STYLES = dict(woman=style_woman, man=style_man, elder=style_elder, child=style_child)

def build(style, HJ, hs, YS, material, colour, matname):
    m = Mesh(); STYLES[style](m)
    co = [(HJ + hs * (np.asarray(v) + [0, YS, 0])).tolist() for v in m.v]
    me = bpy.data.meshes.new('Hair'); me.from_pydata(co, [], m.f); me.update()
    for p in me.polygons: p.use_smooth = True
    ca = me.color_attributes.new('Color', 'BYTE_COLOR', 'CORNER')
    for lp in me.loops:
        s = m.s[lp.vertex_index]; ca.data[lp.index].color = (s, s, s, 1.0)
    me.color_attributes.active_color = ca
    mat = bpy.data.materials.get(matname) or material(matname, colour)
    mat.node_tree.nodes['Mix'].inputs[6].default_value = colour
    me.materials.append(mat)
    ob = bpy.data.objects.new('Hair', me); bpy.context.scene.collection.objects.link(ob)
    import bmesh
    bm = bmesh.new(); bm.from_mesh(me); bmesh.ops.recalc_face_normals(bm, faces=bm.faces); bm.to_mesh(me); bm.free()
    g = ob.vertex_groups.new(name='J_Bip_C_Head'); g.add(list(range(len(co))), 1.0, 'REPLACE')
    return ob
