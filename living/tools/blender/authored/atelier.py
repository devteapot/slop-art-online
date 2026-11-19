"""Near-only fitting of the tide embroiderer's blouse, sculpt and paired temple locks.
Coordinates in the design are metres in the generator's Blender rest frame.
"""
from math import cos, exp, pi, sin

import bmesh
from mathutils import Vector
from mathutils.kdtree import KDTree


def strip(ob, arm, raw, rows, palette, uv_box, facing=(0,1,0)):
    """Bind a folded ribbon to the same joint neighbourhood as its supporting surface."""
    tree = KDTree(len(ob.data.vertices))
    for v in ob.data.vertices:
        tree.insert(v.co, v.index)
    tree.balance()
    pos, weights, colours, uv, faces = [], [], [], [], []
    n = len(rows[0])
    u0, v0, u1, v1 = uv_box
    for i, row in enumerate(rows):
        for j, point in enumerate(row):
            pos.append(point)
            shares = {}
            for _, k, d in tree.find_n(point, 3):
                for g in ob.data.vertices[k].groups:
                    name = ob.vertex_groups[g.group].name
                    shares[name] = shares.get(name, 0) + g.weight / max(d, .0001)**2
            top = sorted(shares, key=shares.get, reverse=True)[:4]
            total = sum(shares[k] for k in top)
            weights.append({k: shares[k]/total for k in top})
            colours.append(palette[j])
            uv.append((u0+(u1-u0)*j/(n-1), v0+(v1-v0)*i/(len(rows)-1)))
            if i and j:
                k = i*n+j
                faces.append((k-n-1, k-n, k, k-1))
    # Every visible front panel faces +Y irrespective of the side it was cut for.
    a,b,c,_ = faces[len(faces)//2]
    if (Vector(pos[b])-Vector(pos[a])).cross(Vector(pos[c])-Vector(pos[a])).dot(Vector(facing)) < 0:
        faces = [f[::-1] for f in faces]
    part = raw(ob.name.split('.')[0], pos, faces, weights, colours,
               ob.data.materials[0].name, arm, uvs=uv)
    if ob.name.split('.')[0]=="Hair":
        grey=part.data.attributes.new("_GREY","FLOAT","POINT")
        ring=part.data.attributes.new("_RING","FLOAT","POINT")
        for k in range(len(pos)):
            t=(k//n)/(len(rows)-1)
            grey.data[k].value=.48
            ring.data[k].value=max(0,1-t*1.6)*.86
    return part


def surface(ob, x, z, offset):
    hit, co, _, _ = ob.ray_cast((x, .5, z), (0, -1, 0))
    if not hit:
        raise ValueError(f"{ob.name} has no front panel at {x:.3f}, {z:.3f}")
    return (x, co.y + offset, z)


def blouse(ob, arm, raw):
    # Two turned-back lapels, two curved princess seams and a pleated centre bib.
    # Raised ridges, seam allowances and contrasting piping share the cloth slot.
    parts = []
    for side in (-1, 1):
        for seam in (False, True):
            rows = []
            for i in range(23):
                t = i/22
                z = (1.38-.60*t) if seam else (1.465-.22*t)
                x = (.078 + .028*cos(2*pi*t) + .025*t) if seam else (.065*(1-t)+.012*t+.027*sin(pi*t))
                width = .005 if seam else .008+.024*sin(pi*t)**.7
                rows.append([surface(ob, side*(x+width*q), z,
                                     .0035+.007*(1-abs(q))) for q in (-1,-.8,0,.8,1)])
            tones = [.78,.93,.80,.98,.64] if seam else [.50,.93,.94,.98,.53]
            parts.append(strip(ob, arm, raw, rows, [(c,c,c) for c in tones], (.51,.02,.98,.98)))
    rows = []
    for i in range(26):
        t=i/25
        z=1.266-.46*t
        width=.024+.038*t
        rows.append([surface(ob, width*(j/8-1), z,
                             .006+(.002+.005*t)*(.5+.5*cos(j*pi/2))) for j in range(17)])
    parts.append(strip(ob,arm,raw,rows,[(.94,.94,.94)]*17,(.02,.02,.48,.98)))
    # Two knife-pleated side panels fall from the high waist. The centre stays
    # open so the embroidered bib and the original cloth can move independently.
    for side in (-1,1):
        rows=[]
        for i in range(13):
            t=i/12
            row=[]
            for j in range(33):
                u=j/32
                angle=side*(.50+2.34*u)
                z=1.13-.443*t+.029*sin(pi*u)*t+.014*cos(8*pi*u)*t
                direction=Vector((sin(angle),cos(angle),0))
                hit,point,_,_=ob.ray_cast((direction.x*.6,direction.y*.6,z),-direction)
                if not hit:
                    raise ValueError(f"uncovered skirt panel at {z:.3f}")
                ridge=.004+.007*t+.013*t*(.5+.5*cos(8*pi*u))**3
                row.append(tuple(point+direction*ridge))
            rows.append(row)
        parts.append(strip(ob,arm,raw,rows,[(.77+.16*cos(j*pi/4),)*3 for j in range(33)],
                           (.51,.02,.98,.98),(side,0,0)))
    # Sailor collar curves around the base of the neck, opens into two
    # points in front and lies across the shoulders toward the back yoke.
    for side in (-1,1):
        rows=[]
        for i in range(28):
            t=i/27
            theta=.16+2.93*t
            row=[]
            for q in (0,.08,.19,.58,.88,1):
                radius=.061+.060*q
                x=side*radius*sin(theta)
                y=.002+radius*cos(theta)
                z=1.494+.012*t-.032*q-.043*q*max(0,cos(theta))**3
                # Vertical projection seats even the wide back edge on the yoke.
                hit,co,_,_=ob.ray_cast((x,y,1.60),(0,0,-1))
                if hit: z=max(z,co.z+.004+.005*sin(pi*q))
                row.append((x,y,z))
            rows.append(row)
        parts.append(strip(ob,arm,raw,rows,[(.82,)*3,(.97,)*3,(.72,)*3,(.94,)*3,(.99,)*3,(.60,)*3],
                           (.54,.06,.95,.26),(0,0,1)))
    # A framed lozenge clasp with a cabochon over the intersection of the lapels.
    rows=[]
    for i in range(13):
        t=i/12
        width=.001+.017*(1-abs(2*t-1))
        rows.append([surface(ob,q*width,1.293-.044*t,.015+.008*(1-abs(q))*sin(pi*t))
                     for q in (-1,-.80,-.55,0,.55,.80,1)])
    parts.append(strip(ob,arm,raw,rows,[(.47,.32,.19),(.99,.82,.53),(.55,.36,.18),(.38,.73,.75),
                                          (.55,.36,.18),(.99,.82,.53),(.47,.32,.19)],
                       (.008,.008,.009,.009)))
    return parts


def locks(ob, arm, raw):
    # Three overlapping leaves at each temple. The asymmetric sweep clears the eye
    # and breaks the stock cap's straight side silhouette at the jaw and collar.
    parts=[]
    for side in (-1,1):
        for leaf in range(3):
            rows=[]
            for i in range(33):
                t=i/32
                x=.039+.066*sin(t*pi*.65)+.009*leaf+.009*sin(2*pi*t+leaf*.5)
                z=1.784-(.26+.035*leaf+side*.019)*t
                y=.045+.060*sin(pi*t*.78)-.011*leaf+.016*t
                width=(.004+.018*sin(pi*t)**.7)*(1-.98*t**5)
                rows.append([(side*(x+q*width),y+.005*(1-q*q),z+.008*q*sin(pi*t))
                             for q in (-1,-.60,-.18,.2,.65,1)])
            palette=[(.48,)*3,(.76,)*3,(.98,)*3,(.92,)*3,(.75,)*3,(.50,)*3]
            parts.append(strip(ob,arm,raw,rows,palette,(.04,.02,.94,.98)))
    # The back is cut as two fans. Each broad leaf has a ridge and a swept,
    # pointed end. The under-fan fills gaps when the springs separate the tips.
    for layer, count in enumerate((17, 21)):
        for leaf in range(count):
            angle=(58+244*leaf/(count-1))*pi/180
            rows=[]
            for i in range(25):
                t=i/24
                az=angle+.12*sin(pi*t+angle)+.055*sin(2*pi*t+leaf)
                opening=min(1,t/.31)
                radial=.019+.105*sin(opening*pi/2)
                z=1.801-(.46+.035*cos(angle)+.026*cos(leaf*1.73)-.025*layer)*t
                # At shoulder level rearward fall clears the shoulder and smock.
                sweep=max(0,min(1,(1.59-z)/.13))
                y=.006+radial*cos(az)-sweep*(.073+.04*max(0,cos(az)))
                wide=(.005+.029*sin(min(1,t/.22)*pi/2))*(1-.97*t**6)
                rows.append([(radial*sin(az)+q*wide*cos(az)+layer*.006*sin(az),
                              y-q*wide*sin(az)+(layer*.006+.004*(1-q*q))*cos(az),
                              z+q*.005*sin(pi*t)) for q in (-1,-.52,0,.52,1)])
            tones=(.53,.79,.97,.84,.62) if layer else (.42,.59,.72,.62,.46)
            parts.append(strip(ob,arm,raw,rows,[(c,)*3 for c in tones],(.03,.03,.97,.98),
                               (sin(angle),cos(angle),0)))
    # Continuous under-fringe: its top curls over the crown, and the tips
    # of the five outer leaves can move apart without exposing a bald strip.
    rows=[]
    for i in range(19):
        t=i/18
        row=[]
        for j in range(25):
            q=j/12-1
            x=q*(.063+.036*t)-.008*(1-t)
            z=1.795-.088*t-.044*q*q+.004*sin(2*pi*q)*t
            y=.021+.081*sin(t*pi*.54)-.041*q*q+.004*cos(q*5*pi)
            row.append((x,y,z))
        rows.append(row)
    parts.append(strip(ob,arm,raw,rows,[(.70+.055*cos(j*pi/3),)*3 for j in range(25)],
                       (.03,.11,.98,.97)))
    for leaf,end in enumerate((-.078,-.048,-.012,.030,.073)):
        rows=[]
        for i in range(24):
            t=i/23
            x=-.046*(1-t)+end*t+.014*sin(pi*t)
            z=1.793-(.117+.010*cos(leaf*1.83))*t
            y=.039+.074*sin(t*pi*.55)-.023*(abs(x)/.08)**2
            w=(.010+.021*sin(pi*t)**.60)*(1-.89*t**6)
            rows.append([(x+q*w,y+.005*(1-q*q),z+.009*q*t) for q in (-1,-.45,0,.55,1)])
        parts.append(strip(ob,arm,raw,rows,[(c,)*3 for c in (.56,.83,.98,.89,.67)],(.08,.12,.86,.94)))
    # Keep only the shared scalp. The donor strips were weight-transfer guides.
    m=bmesh.new()
    m.from_mesh(ob.data)
    m.verts.ensure_lookup_table()
    bmesh.ops.delete(m, geom=list(m.verts)[ob["scalp_vertices"]:], context='VERTS')
    m.to_mesh(ob.data)
    m.free()
    return parts


def sculpt(ob, maturity):
    # Move the expression library with its basis so the lip and lid seals survive.
    keys = ob.data.shape_keys
    # This design key exists on the editable Blender source. Bake its chosen
    # value into all expressions for export so a client needs no new morph driver.
    basis = keys.key_blocks[0]
    design = ob.shape_key_add(name="Atelier cheek and chin", from_mix=False)
    for v in design.data:
        x,y,z=v.co
        front=min(1,max(0,y/.045))
        cheek=exp(-((abs(x)-.058)/.027)**2-((z-1.614)/.032)**2)
        jaw=exp(-((z-1.555)/.020)**2)
        bridge=exp(-(x/.015)**2-((z-1.625)/.032)**2)
        v.co.x *= 1-.08*jaw*front
        v.co.y += front*(.005*cheek+.0025*bridge)
    # Store the unit sculpt as a point-domain vector for the editable master.
    # A prefixed lowercase attribute stays in Blender and is skipped by glTF.
    unit = ob.data.attributes.new("atelier_profile", "FLOAT_VECTOR", "POINT")
    # Adding an attribute can invalidate Blender RNA wrappers.
    design = keys.key_blocks["Atelier cheek and chin"]
    basis = keys.key_blocks[0]
    changes = [v.co-b.co for v,b in zip(design.data,basis.data)]
    for a,d in zip(unit.data,changes):
        a.vector = d
    ob["atelier_maturity"] = maturity
    deltas=[d*maturity for d in changes]
    ob.shape_key_remove(design)
    for key in keys.key_blocks:
        for v,d in zip(key.data,deltas):
            v.co+=d
    return


def dress(parts, arm, spec, raw):
    source={o.name.split('.')[0]:o for o in parts}
    sculpt(source['Face'], .36 if (spec.get('type') or '').startswith('youth') else .92)
    if 'Hands' in source:
        # Shape the dorsal knuckles and narrow the wrist transition in the rest cage.
        hand=source['Hands']
        for v in hand.data.vertices:
            x,y,z=v.co
            swell=exp(-((abs(x)-.853)/.024)**2)
            v.co.z+=.0025*swell*min(1,max(0,(z-1.43)/.018))
    if 'Hair' in source:
        parts.extend(locks(source['Hair'],arm,raw))
    if 'Smock' in source:
        parts.extend(blouse(source['Smock'],arm,raw))
