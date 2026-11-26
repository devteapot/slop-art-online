"""Finger sockets share their web edges. Each wrist joins directly to its sleeve."""
import math
from mathutils import Vector


def build_hand(side, sign, wrist, rig, points, vertex, quad, bridge, aligned):
    prefix = 'J_Bip_' + side + '_'
    hand = prefix + 'Hand'
    forearm = prefix + 'LowerArm'
    fingers = ('Index', 'Middle', 'Ring', 'Little')
    across = Vector((-.56 * sign, .828, 0)).normalized()
    dorsal = Vector((.828 * sign, .56, 0)).normalized()

    def joint(name):
        return rig.matrix_world @ rig.data.bones[prefix + name].head_local

    # Around each section, nine stations down the back, the ulnar edge,
    # nine back across the palm, then the radial edge around the thumb.
    uv = ([(i / 4 - 1, 1) for i in range(9)]
          + [(1, v) for v in (.5, 0, -.5)]
          + [(1 - i / 4, -1) for i in range(9)]
          + [(-1, v) for v in (-.5, 0, .5)])
    rows = []
    # height, lateral centre, half breadth, thickness and wrist flex
    for z, cx, cy, width, depth, wrist_share in [
        (.901, .271, -.015, .021, .016, .65),
        (.890, .273, -.014, .023, .015, .28),
        (.872, .275, -.013, .030, .017, .05),
        (.853, .277, -.012, .036, .018, 0),
        (.839, .278, -.010, .037, .016, 0),
        (.827, .277, -.008, .037, .012, 0),
    ]:
        ring = []
        for u,v in uv:
            corner = abs(u)**4 * abs(v)**2
            centre = Vector((cx*sign,cy,z))
            p = centre + across*(u*width*(1-.060*corner))
            p += dorsal*(v*depth*(1-.37*u*u))
            # Shorter little metacarpal, convex knuckles and a cupped palm.
            p.z += .005 * u*u * max(0, (.87-z)/.043)
            p += dorsal*(.0024*(1-u*u)*max(0, (.89-z)/.063))
            ring.append(vertex(tuple(p), {hand:1-wrist_share, forearm:wrist_share}))
        rows.append(ring)
    bridge(wrist, aligned(wrist, rows[0]), 3)
    for r,(a,b) in enumerate(zip(rows,rows[1:])):
        for k in range(24):
            if r in (1,2) and k in (20,21,22,23):
                continue
            q=(k+1)%24
            quad(a[k],a[q],b[q],b[k],3)

    end=rows[-1]
    # Continuous tunnels branching off the end of the palm.
    divisions={0:[end[i] for i in (0,23,22,21,20)],4:[end[i] for i in (8,9,10,11,12)]}
    for i in range(1,4):
        back,front=end[2*i],end[20-2*i]
        inner=[]
        for t in (.25,.5,.75):
            p=Vector(points[back]).lerp(Vector(points[front]),t)
            p.z-=.004*math.sin(math.pi*t)
            inner.append(vertex(tuple(p),{hand:1}))
        divisions[i]=[back,*inner,front]

    def digit(name, socket, breadth):
        j1,j2,j3=(joint(name+str(i)) for i in (1,2,3))
        axis=(j3-j1).normalized()
        wide=(across-axis*across.dot(axis)).normalized()
        normal=wide.cross(axis).normalized()
        if normal.dot(dorsal)<0:
            normal=-normal
        n=len(socket)
        root=Vector((0,0,0))
        for v in socket:
            root+=Vector(points[v])/n
        # Three segments with support rings on either side of the two creases.
        # The fingertip pad and nail taper independently of the knuckle.
        stations=[
            (root.lerp(j2,.22), 1.05, .94, 1, .08),
            (j2-axis*.005, .92, .90, 1, .22),
            (j2+axis*.003, .93, .90, 1, .70),
            (j2+axis*.009, .84, .82, 2, 0),
            (j3-axis*.004, .79, .79, 2, .20),
            (j3+axis*.003, .79, .77, 2, .72),
            (j3+axis*.010, .75, .70, 3, 0),
            (j3+axis*.018, .61, .56, 3, 0),
            (j3+axis*.021, .38, .42, 3, 0),
        ]
        previous=socket
        for r,(centre,b,h,segment,t) in enumerate(stations):
            influences={prefix+name+str(segment):1-t}
            if t:
                influences[prefix+name+str(segment+1)]=t
            ring=[]
            for k in range(n):
                a=math.tau*k/n
                p=centre+wide*(breadth*b*math.sin(a))+normal*(breadth*h*math.cos(a))
                ring.append(vertex(tuple(p),influences))
            ring=aligned(previous,ring)
            for k in range(n):
                q=(k+1)%n
                outward=(Vector(points[ring[k]])+Vector(points[ring[q]]))*.5-centre
                slot=4 if r in (7,8) and outward.dot(normal)>.48*breadth else 3
                quad(previous[k],previous[q],ring[q],ring[k],slot)
            previous=ring
        # A rounded quad fan closes the padded tip.
        tip=vertex(tuple(centre+axis*.002),influences)
        for k in range(0,n,2):
            quad(previous[k],previous[(k+1)%n],previous[(k+2)%n],tip,3)

    for i,name in enumerate(fingers):
        lo=2*i
        socket=([end[lo],end[lo+1],end[lo+2]]+divisions[i+1][1:]
                +[end[19-lo],end[20-lo]]+divisions[i][-2:0:-1])
        digit(name,socket,(.0086,.0090,.0082,.0071)[i])
    rim=([rows[1][i] for i in (20,21,22,23,0)]+[rows[2][0],rows[3][0]]
         +[rows[3][i] for i in (23,22,21,20)]+[rows[2][20]])
    digit('Thumb',rim,.0102)
