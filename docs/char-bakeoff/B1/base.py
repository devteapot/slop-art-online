"""Build the first-round fitting body from section drawings in metres, Blender Z up."""
import math
import os
import runpy
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
SOURCE = REPO / 'docs/char-live-3/ink-batch-2'
OUT = Path(os.environ['B1_OUT']).resolve()
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0,str(HERE))
from hands import build_hand

bpy.ops.wm.open_mainfile(filepath=str(SOURCE/'cora-final.blend'))
rig = bpy.data.objects['Armature']
for obj in list(bpy.context.scene.objects):
    if obj.type == 'MESH' and (obj.hide_render or not any(
        word in obj.name for word in ['Face', 'neck and', 'swept hair']
    )):
        bpy.data.objects.remove(obj, do_unlink=True)

points, faces, slots, weights = [], [], [], []
TAU = math.tau
N = 40


def vertex(point, influences):
    points.append(point)
    weights.append(influences)
    return len(points)-1


def blend(z, stations):
    """Linear joint envelopes, in station order. Weights sum to one."""
    if z <= stations[0][0]:
        return {stations[0][1]: 1}
    for (low, a), (high, b) in zip(stations,stations[1:]):
        if z <= high:
            t = (z-low)/(high-low)
            if a == b:
                return {a:1}
            return {a:1-t,b:t}
    return {stations[-1][1]:1}


def quad(a,b,c,d,slot):
    faces.append((a,b,c,d))
    slots.append(slot)


def bridge(a,b,slot):
    assert len(a)==len(b)
    for i in range(len(a)):
        k=(i+1)%len(a)
        quad(a[i],a[k],b[k],b[i],slot)


def aligned(a,b):
    """Rotate and wind an irregular opening onto its matching section by arc order."""
    def distance(loop):
        return sum((Vector(points[i])-Vector(points[j])).length_squared for i,j in zip(a,loop))
    return min((seq[k:]+seq[:k] for seq in (b,b[::-1]) for k in range(len(b))),key=distance)


hips,spine,chest,upper = ['J_Bip_C_'+name for name in ('Hips','Spine','Chest','UpperChest')]
axial=[(.94,hips),(1.077,spine),(1.195,chest),(1.31,upper)]
# Front and back depths are independent. The hem is the common edge of both leg sockets.
trunk=[
 (.820,.139,.079,.098),(.858,.150,.091,.105),(.895,.153,.099,.112),
 (.936,.150,.102,.110),(.985,.136,.098,.095),(1.026,.119,.091,.083),
 (1.063,.110,.088,.077),(1.096,.112,.088,.078),(1.13,.119,.089,.085),
 (1.16,.127,.092,.091),(1.19,.134,.104,.095),(1.222,.141,.115,.097),
 (1.247,.146,.118,.095),(1.272,.150,.108,.092),(1.302,.155,.090,.089),
 (1.327,.157,.079,.081),(1.348,.141,.073,.071),(1.366,.101,.062,.063),
 (1.382,.061,.052,.058),(1.39,.054,.048,.055),(1.389,.048,.044,.049),(1.386,.038,.037,.039)]
rings=[]
bottom,top=12,16
port,starboard=10,30
half=4
for z,rx,front,back in trunk:
    row=[]
    for k in range(N):
        t=TAU*k/N
        x=rx*math.sin(t)
        c=math.cos(t)
        y=-(front if c>0 else back)*c
        # Pectoral and abdominal planes and the paired volume of the seat.
        if c>0:
            breast = math.exp(-((abs(x)-.071)/.041)**2-((z-1.235)/.047)**2)
            y-=.014*breast*c
            y+=.006*math.exp(-(x/.018)**2-((z-1.23)/.060)**2)
        else:
            y+=.014*math.exp(-((abs(x)-.071)/.045)**2-((z-.88)/.064)**2)*(-c)
        dz=-.025*abs(c)**4 if z==trunk[0][0] else 0
        if 1.02<z<1.10: dz-=.009*c*c
        row.append(vertex((x,y,z+dz),blend(z,axial)))
    rings.append(row)
for r in range(len(rings)-1):
    for i in range(N):
        if bottom<=r<top and any(s-half<=i<s+half for s in (port,starboard)):
            continue
        k=(i+1)%N
        slot=1 if r<=5 else (2 if r in (6,18,19,20) else 0)
        quad(rings[r][i],rings[r][k],rings[r+1][k],rings[r+1][i],slot)

# One curved strip from pubis to seat divides the hip opening into two thigh loops.
front_pt,back_pt=points[rings[0][0]],points[rings[0][N//2]]
saddle=[rings[0][0]]
for k in range(1,8):
    f=k/8
    saddle.append(vertex((0,front_pt[1]*(1-f)+back_pt[1]*f,
                          front_pt[2]-.012*math.sin(math.pi*f)),{hips:1}))
saddle.append(rings[0][N//2])

# Leg stations silhouette the trochanter, patella, calf, ankle and ball of the foot.
legs=[
 (.753,.077,.066,.082,.005),(.719,.080,.066,.079,.004),(.675,.084,.064,.074,.002),(.659,.085,.064,.073,.001),
 (.654,.086,.063,.072,.001),
 (.615,.091,.058,.064,-.002),(.549,.095,.050,.055,-.003),(.507,.098,.045,.049,-.005),
 (.483,.099,.043,.047,-.008),(.464,.100,.044,.047,-.008),(.445,.101,.042,.044,-.001),
 (.409,.102,.045,.050,.008),(.366,.104,.050,.060,.017),(.315,.108,.049,.059,.019),
 (.264,.111,.042,.050,.016),(.205,.114,.033,.040,.012),(.182,.115,.032,.038,.011),(.174,.116,.031,.036,.010),(.152,.117,.027,.032,.009),
 (.111,.119,.027,.031,.007),(.089,.120,.031,.041,.003),(.069,.122,.037,.066,-.017),
 (.049,.125,.046,.095,-.048),(.031,.126,.049,.108,-.057),(.015,.126,.049,.105,-.057),
 (.009,.126,.044,.098,-.057)]
arms=[
 (1.314,.153,.005,.040,.046),(1.303,.164,.007,.042,.046),
 (1.283,.172,.008,.041,.045),(1.248,.181,.009,.039,.043),
 (1.203,.190,.008,.035,.040),(1.160,.201,.006,.030,.035),
 (1.137,.205,.005,.028,.030),(1.121,.209,.006,.028,.030),
 (1.104,.213,.004,.029,.031),(1.079,.219,.002,.031,.034),
 (1.044,.229,-.001,.030,.034),(1.001,.241,-.006,.026,.029),
 (.958,.254,-.011,.021,.024),(.928,.267,-.014,.024,.024),
 (.915,.270,-.014,.024,.026),(.904,.271,-.015,.024,.026)]
for side,sgn,s in [('L',1,port),('R',-1,starboard)]:
    prefix='J_Bip_'+side+'_'
    upperleg,shin,foot=[prefix+n for n in ('UpperLeg','LowerLeg','Foot')]
    leg_weights=[(.085,foot),(.124,shin),(.435,shin),(.506,upperleg),(.756,upperleg),(.859,hips)]
    outer=[rings[0][(sgn*k)%N] for k in range(N//2+1)]
    previous=outer+saddle[-2:0:-1]
    for z,x,rx,ry,cy in legs:
        loop=[]
        for k in range(len(previous)):
            t=TAU*k/len(previous)
            # The toe box widens on the medial side, narrows at the heel.
            width=1+(.12*math.cos(t) if z<.07 else 0)
            loop.append(vertex((sgn*(x+rx*width*math.sin(t)),cy-ry*math.cos(t)-.007*math.exp(-((z-.479)/.031)**2)*max(0,math.cos(t))**3,z),
                               blend(z,leg_weights)))
        loop=aligned(previous,loop)
        if z>=.659: slot=1
        elif z>=.654: slot=2
        elif z>=.182: slot=3
        elif z>=.174: slot=2
        else: slot=1
        bridge(previous,loop,slot)
        previous=loop
    # Across-foot quads support the toe roll without a single polygon
    # spanning the entire sole. The two ends close with a triangle each.
    tip=min(range(len(previous)),key=lambda i:points[previous[i]][1])
    sole=previous[tip:]+previous[:tip]
    half_sole=len(sole)//2
    faces.append((sole[0],sole[1],sole[-1])); slots.append(1)
    for k in range(1,half_sole-1):
        quad(sole[k],sole[k+1],sole[-k-1],sole[-k],1)
    faces.append((sole[half_sole-1],sole[half_sole],sole[half_sole+1])); slots.append(1)
    low=s-half; high=s+half
    previous=(rings[bottom][low:high+1]+[rings[r][high] for r in range(bottom+1,top+1)]
              +rings[top][low:high][::-1]+[rings[r][low] for r in range(top-1,bottom,-1)])
    shoulder,arm,forearm,hand=[prefix+n for n in ('Shoulder','UpperArm','LowerArm','Hand')]
    for idx in previous:
        x,y,z=points[idx]
        w=.22+.29*max(0,(z-1.25)/.10)
        weights[idx]={upper:1-w,shoulder:w}
    for r,(z,x,cy,rx,ry) in enumerate(arms):
        loop=[]
        influences=blend(z,[(.892,hand),(.923,forearm),(1.098,forearm),(1.145,arm),
                            (1.3,arm),(1.36,shoulder)])
        # Deltoid cap starts nearly vertical at its socket and turns into the arm.
        slope=[.69,.59,.43,.34][min(r,3)]
        for k in range(len(previous)):
            t=TAU*k/len(previous)
            loop.append(vertex((sgn*(x+rx*math.sin(t)),cy-ry*math.cos(t),
                                z+rx*slope*math.sin(t)),influences))
        loop=aligned(previous,loop)
        bridge(previous,loop,2 if r in (14,15) else 0)
        previous=loop

    build_hand(side,sgn,previous,rig,points,vertex,quad,bridge,aligned)

# Smooth the crotch as a shared patch. At its saddle, both upper legs
# contribute. Their share tapers continuously toward the outer hip and waist.
def ramp(t):
    t=max(0.,min(1.,t))
    return t*t*(3.-2.*t)
for i,(x,y,z) in enumerate(points):
    if z<.083:
        side='L' if x>0 else 'R'
        toe=ramp((-.047-y)/.071)*ramp((.083-z)/.029)
        weights[i]={n:w*(1-toe) for n,w in weights[i].items()}
        weights[i]['J_Bip_'+side+'_ToeBase']=toe
    if .62<z<.98 and abs(x)<.186:
        thigh=ramp((.965-z)/.245)
        half_width=.078*ramp((z-.625)/.164)
        left=ramp(.5+.5*x/max(.0001,half_width))
        weights[i]={hips:1-thigh,'J_Bip_L_UpperLeg':thigh*left,'J_Bip_R_UpperLeg':thigh*(1-left)}
    if 1.255<z<1.365 and abs(x)>.077:
        side='L' if x>0 else 'R'
        lateral=ramp((abs(x)-.077)/.110)
        arm_share=ramp((abs(x)-.108)/.085)
        amount=ramp((z-1.255)/.025)*ramp((1.365-z)/.02)
        smooth={upper:1-lateral,'J_Bip_'+side+'_Shoulder':lateral*(1-arm_share),
                'J_Bip_'+side+'_UpperArm':lateral*arm_share}
        original=weights[i]
        weights[i]={n:original.get(n,0)*(1-amount)+smooth.get(n,0)*amount
                    for n in set(original)|set(smooth)}

# Only used points become vertices, including around the shoulder holes.
used=sorted({i for poly in faces for i in poly})
remap={old:new for new,old in enumerate(used)}
mesh=bpy.data.meshes.new('Fitting body | quad cage')
mesh.from_pydata([points[i] for i in used],[],[[remap[i] for i in poly] for poly in faces])
mesh.update()
body=bpy.data.objects.new('Base | jersey, shorts and socks',mesh)
bpy.context.collection.objects.link(body)
body.parent=rig
body.matrix_parent_inverse=rig.matrix_world.inverted()
for name,colour in [('Undershirt',(.17,.26,.26)),('Shorts and socks',(.080,.106,.117)),('Rib knit',(.18,.22,.20)),('Exposed skin',(.828,.470,.301)),('Nail bed',(.855,.526,.411))]:
    mat=bpy.data.materials.new(name)
    mat.diffuse_color=(*colour,1)
    mat.use_nodes=True
    shader=mat.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Base Color'].default_value=mat.diffuse_color
    shader.inputs['Roughness'].default_value=.91
    mesh.materials.append(mat)
for poly,slot in zip(mesh.polygons,slots):
    poly.material_index=slot
    poly.use_smooth=True
for i,old in enumerate(used):
    for bone,w in weights[old].items():
        if w>0:
            group=body.vertex_groups.get(bone) or body.vertex_groups.new(name=bone)
            group.add([i],w,'REPLACE')
bm=bmesh.new()
bm.from_mesh(mesh)
bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
bm.to_mesh(mesh)
bm.free()
sub=body.modifiers.new('Rounded fitting surface','SUBSURF')
sub.levels=sub.render_levels=1
skin=body.modifiers.new('Shared clips','ARMATURE')
skin.object=rig
bpy.context.view_layer.update()
bpy.ops.object.select_all(action='DESELECT')
body.select_set(True)
rig.select_set(True)
bpy.context.view_layer.objects.active=body
bpy.context.preferences.filepaths.save_version=0
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'base.blend'),compress=True)
runpy.run_path(str(HERE / "export_body.py"), run_name="__main__")
